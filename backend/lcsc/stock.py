"""
LCSC stock check and equivalent replacement.

For each component:
1. Check current stock via jlcsearch
2. If stock < threshold, search for equivalent replacement
3. Return stock status + replacement info per component
"""

from __future__ import annotations
import logging
import re
from typing import List, Optional, Tuple

import httpx

from .search import search_components, find_best_match, lcsc_number_to_part_uuid, JLCSEARCH_BASE
from models.circuit import BaseComponent, CircuitError

logger = logging.getLogger(__name__)

DEFAULT_MIN_STOCK = 100


async def check_component_stock(
    lcsc_number: Optional[str],
    search_query: Optional[str] = None,
) -> Optional[dict]:
    """
    Look up current stock for an LCSC part number.
    Returns the component data dict from jlcsearch or None.
    """
    if not lcsc_number:
        return None

    # Normalize LCSC number
    lcsc_str = str(lcsc_number).strip().upper()
    if not lcsc_str.startswith("C"):
        lcsc_str = f"C{lcsc_str}"

    # Try to find by LCSC number directly
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            resp = await client.get(
                f"{JLCSEARCH_BASE}/components/list.json",
                params={"search": lcsc_str, "full": "true"},
            )
            if resp.status_code == 200:
                data = resp.json()
                items = data if isinstance(data, list) else data.get("components", data.get("results", []))
                for item in items:
                    # Match by exact LCSC number
                    item_lcsc = str(item.get("lcsc", "")).upper()
                    if not item_lcsc.startswith("C"):
                        item_lcsc = f"C{item_lcsc}"
                    if item_lcsc == lcsc_str:
                        return item
        except Exception as e:
            logger.warning(f"Stock check for {lcsc_str} failed: {e}")

    return None


def _extract_key_specs(component: BaseComponent) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Extract key specs from a component for equivalent search:
    Returns (value, package_hint, category_hint).
    """
    value = component.value
    query = component.search_query

    # Try to detect package from query or value
    package_patterns = [
        r'\b(0402|0603|0805|1206|1210|2010|2512)\b',
        r'\b(SOT-23|SOT23|SOT-223|TO-92|TO-220|TO-263)\b',
        r'\b(SOIC-8|SOIC-16|DIP-8|DIP-16|QFN|QFP|TSSOP)\b',
        r'\b(SMA|SMB|SMC|DO-214)\b',
    ]
    package = None
    for pat in package_patterns:
        match = re.search(pat, (query or "") + " " + (value or ""), re.IGNORECASE)
        if match:
            package = match.group(1)
            break

    # Detect category from designator prefix
    designator = component.designator or ""
    category_map = {
        "R": "resistor",
        "C": "capacitor",
        "L": "inductor",
        "D": "diode",
        "Q": "transistor",
        "U": "IC",
        "J": "connector",
        "X": "crystal",
        "SW": "switch",
        "F": "fuse",
    }
    category = None
    for prefix, cat in category_map.items():
        if designator.upper().startswith(prefix):
            category = cat
            break

    return value, package, category


async def find_equivalent(
    component: BaseComponent,
    min_stock: int = DEFAULT_MIN_STOCK,
) -> Optional[dict]:
    """
    Find an equivalent in-stock replacement for a component.
    
    Strategy:
    1. Use the search_query to find alternatives
    2. Filter to components with stock >= min_stock
    3. Prefer same package
    4. Return best match
    """
    value, package, category = _extract_key_specs(component)

    # Build search queries in order of specificity
    queries = []
    if component.search_query:
        queries.append(component.search_query)
    if value and category:
        queries.append(f"{value} {category}")
    if value:
        queries.append(value)

    for query in queries:
        results = await search_components(query, limit=20, in_stock_only=False)
        # Filter by stock
        good_stock = [r for r in results if r.get("stock", 0) >= min_stock]
        if not good_stock:
            continue

        # Prefer same package
        if package:
            pkg_lower = package.lower()
            pkg_matches = [r for r in good_stock if pkg_lower in r.get("package", "").lower()]
            if pkg_matches:
                return pkg_matches[0]

        return good_stock[0]

    return None


class StockStatus:
    OK = "ok"
    LOW = "low"
    OUT = "out"
    UNKNOWN = "unknown"
    REPLACED = "replaced"


async def check_and_replace_components(
    components: List[BaseComponent],
    min_stock: int = DEFAULT_MIN_STOCK,
) -> Tuple[List[BaseComponent], List[CircuitError]]:
    """
    For each component in the list:
    1. Check current stock using its part_uuid/search_query
    2. If stock is insufficient, find an equivalent
    3. Return updated component list + error/info messages
    
    Returns (updated_components, errors).
    """
    # Quick check: if circuit breaker is open, skip stock check entirely
    from lcsc.search import _check_breaker
    if not _check_breaker():
        logger.info("LCSC circuit breaker open — skipping stock check entirely")
        return components, []

    updated: List[BaseComponent] = []
    errors: List[CircuitError] = []

    for comp in components:
        comp_data = comp.model_dump()
        updated_comp = BaseComponent(**comp_data)

        # Try to get LCSC number from part_uuid or search
        lcsc_raw = comp.part_uuid  # might be a uuid or might be a C-number
        stock_info = None

        if lcsc_raw:
            # part_uuid might be a 32-char hex or a raw C-number
            if len(lcsc_raw) <= 10 and (lcsc_raw.upper().startswith("C") or lcsc_raw.isdigit()):
                # It looks like a raw LCSC number
                stock_info = await check_component_stock(lcsc_raw, comp.search_query)
            else:
                # It's a UUID hex — skip direct LCSC lookup, use search instead
                pass

        if not stock_info and comp.search_query:
            # Search by query to find current stock
            results = await search_components(comp.search_query, limit=5)
            if results:
                stock_info = results[0]

        if stock_info:
            stock = stock_info.get("stock", 0)
            lcsc_num = stock_info.get("lcsc_number", "")
            new_uuid = stock_info.get("part_uuid")

            if stock >= min_stock:
                # Good stock — update part_uuid if we got a better one
                if new_uuid and not updated_comp.part_uuid:
                    updated_comp = BaseComponent(**{**comp_data, "part_uuid": new_uuid})
                errors.append(CircuitError(
                    component=comp.designator,
                    error=f"Found {lcsc_num}, stock: {stock} units",
                    severity="info",
                ))
            elif stock > 0:
                # Low stock — report and try to find equivalent
                errors.append(CircuitError(
                    component=comp.designator,
                    error=f"{lcsc_num} has low stock ({stock} units). Searching for equivalent...",
                    severity="warning",
                ))
                equiv = await find_equivalent(comp, min_stock)
                if equiv:
                    new_comp_data = {
                        **comp_data,
                        "part_uuid": equiv["part_uuid"],
                    }
                    updated_comp = BaseComponent(**new_comp_data)
                    errors.append(CircuitError(
                        component=comp.designator,
                        error=(
                            f"Replaced low-stock {lcsc_num} with {equiv['lcsc_number']} "
                            f"({equiv['description'][:60]}, stock: {equiv['stock']})"
                        ),
                        severity="info",
                    ))
            else:
                # Out of stock
                errors.append(CircuitError(
                    component=comp.designator,
                    error=f"{lcsc_num} is out of stock. Searching for equivalent...",
                    severity="warning",
                ))
                equiv = await find_equivalent(comp, min_stock)
                if equiv:
                    new_comp_data = {
                        **comp_data,
                        "part_uuid": equiv["part_uuid"],
                    }
                    updated_comp = BaseComponent(**new_comp_data)
                    errors.append(CircuitError(
                        component=comp.designator,
                        error=(
                            f"Replaced out-of-stock {lcsc_num} with {equiv['lcsc_number']} "
                            f"({equiv['description'][:60]}, stock: {equiv['stock']})"
                        ),
                        severity="info",
                    ))
                else:
                    errors.append(CircuitError(
                        component=comp.designator,
                        error=f"No equivalent found for {comp.designator} ({comp.value}). Manual selection required.",
                        severity="error",
                    ))
        else:
            errors.append(CircuitError(
                component=comp.designator,
                error=f"Could not verify stock for {comp.designator} ({comp.value}). Using provided part_uuid.",
                severity="info",
            ))

        updated.append(updated_comp)

    return updated, errors
