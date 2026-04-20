"""
LCSC component search via jlcsearch.tscircuit.com (free, no auth required).

Endpoints:
  - GET https://jlcsearch.tscircuit.com/components/list.json?search={query}&full=true
  - GET https://jlcsearch.tscircuit.com/resistors/list.json?...
  - GET https://jlcsearch.tscircuit.com/capacitors/list.json?...
  - etc.

The part UUID used by EasyEDA is the LCSC component number reformatted as a
32-char hex string without hyphens (e.g., "C123456" → MD5/UUID-style hex).
jlcsearch returns a field called "lcsc" which is the numeric LCSC number.
We convert it to the EasyEDA part_uuid format.
"""

from __future__ import annotations
import hashlib
import logging
import re
import time
from typing import List, Optional, Dict, Any

import httpx

logger = logging.getLogger(__name__)

JLCSEARCH_BASE = "https://jlcsearch.tscircuit.com"

# ---------------------------------------------------------------------------
# Circuit breaker — after repeated failures, skip LCSC lookups temporarily
# ---------------------------------------------------------------------------
_circuit_breaker: Dict[str, Any] = {"failures": 0, "last_failure": 0.0, "open": False}
BREAKER_THRESHOLD = 3
BREAKER_RESET_SECONDS = 300  # 5 minutes


def _check_breaker() -> bool:
    """Returns True if requests should be allowed."""
    if not _circuit_breaker["open"]:
        return True
    if time.time() - _circuit_breaker["last_failure"] > BREAKER_RESET_SECONDS:
        _circuit_breaker["open"] = False
        _circuit_breaker["failures"] = 0
        logger.info("LCSC circuit breaker RESET — allowing requests again")
        return True
    return False


def _record_failure():
    _circuit_breaker["failures"] += 1
    _circuit_breaker["last_failure"] = time.time()
    if _circuit_breaker["failures"] >= BREAKER_THRESHOLD:
        _circuit_breaker["open"] = True
        logger.warning("LCSC circuit breaker OPEN — skipping further lookups for 5 minutes")


def _record_success():
    _circuit_breaker["failures"] = 0
    _circuit_breaker["open"] = False

# Map common component keywords to category endpoints for better results
CATEGORY_KEYWORDS: Dict[str, str] = {
    "resistor": "resistors",
    "capacitor": "capacitors",
    "inductor": "inductors",
    "led": "leds",
    "diode": "diodes",
    "transistor": "transistors",
    "mosfet": "transistors",
    "bjt": "transistors",
    "connector": "connectors",
    "crystal": "crystals",
    "oscillator": "crystals",
    "relay": "relays",
    "switch": "switches",
    "fuse": "fuses",
    "regulator": "voltage-regulators",
    "ldo": "voltage-regulators",
    "microcontroller": "microcontrollers",
    "mcu": "microcontrollers",
    "op-amp": "op-amps",
    "opamp": "op-amps",
}


def lcsc_number_to_part_uuid(lcsc_number: Any) -> str:
    """
    Convert a LCSC part number to a 32-char hex UUID for EasyEDA.
    
    EasyEDA stores LCSC components with UUIDs that are 32-char hex strings.
    We generate a deterministic UUID from the LCSC number using MD5.
    
    Examples:
      "C123456" → md5("C123456") as 32-char hex
       123456   → md5("C123456") as 32-char hex
    """
    if isinstance(lcsc_number, int):
        lcsc_str = f"C{lcsc_number}"
    else:
        lcsc_str = str(lcsc_number).strip()
        if not lcsc_str.upper().startswith("C"):
            lcsc_str = f"C{lcsc_str}"
        else:
            lcsc_str = lcsc_str.upper()

    # Use MD5 to create a deterministic 32-char hex string
    return hashlib.md5(lcsc_str.encode()).hexdigest()


def detect_category(query: str) -> Optional[str]:
    """
    Detect the component category from a search query string.
    Returns a category path segment or None.
    """
    query_lower = query.lower()
    for keyword, category in CATEGORY_KEYWORDS.items():
        if keyword in query_lower:
            return category
    return None


def parse_component(raw: dict) -> Optional[dict]:
    """
    Parse a raw component dict from jlcsearch into a normalized structure.
    Returns None if the component is missing essential fields.
    """
    lcsc = raw.get("lcsc") or raw.get("number") or raw.get("id")
    if not lcsc:
        return None

    mfr = raw.get("mfr") or raw.get("manufacturer") or ""
    package = raw.get("package") or raw.get("footprint") or ""
    description = raw.get("description") or raw.get("desc") or ""
    stock = raw.get("stock", 0)
    in_stock = raw.get("in_stock", stock > 0)

    # Price — use minimum price in USD
    price = None
    price_list = raw.get("price") or []
    if isinstance(price_list, list) and price_list:
        try:
            prices = [float(p.get("price", 0)) for p in price_list if p.get("price")]
            if prices:
                price = min(prices)
        except (TypeError, ValueError):
            pass
    elif isinstance(price_list, (int, float)):
        price = float(price_list)

    part_uuid = lcsc_number_to_part_uuid(lcsc)

    return {
        "lcsc": str(lcsc),
        "lcsc_number": f"C{lcsc}" if not str(lcsc).upper().startswith("C") else str(lcsc).upper(),
        "part_uuid": part_uuid,
        "mfr": mfr,
        "mfr_part": raw.get("mfr_part") or raw.get("mfrPart") or "",
        "package": package,
        "description": description,
        "stock": stock,
        "in_stock": in_stock,
        "price_usd": price,
    }


async def search_components(
    query: str,
    limit: int = 10,
    in_stock_only: bool = False,
) -> List[dict]:
    """
    Search LCSC components via jlcsearch.tscircuit.com.
    
    Strategy:
    1. Try category-specific endpoint if query contains a known keyword
    2. Fall back to generic /components/list.json
    3. Return parsed + filtered results
    """
    # Check circuit breaker before making any HTTP calls
    if not _check_breaker():
        logger.debug(f"LCSC circuit breaker open — skipping search for '{query}'")
        return []

    results: List[dict] = []
    seen_lcsc: set = set()

    async with httpx.AsyncClient(timeout=5.0) as client:
        # Step 1: Category search (often more accurate)
        category = detect_category(query)
        if category:
            url = f"{JLCSEARCH_BASE}/{category}/list.json"
            try:
                resp = await client.get(url, params={"search": query, "full": "true"})
                if resp.status_code == 200:
                    _record_success()
                    data = resp.json()
                    items = data if isinstance(data, list) else data.get("components", data.get("results", []))
                    for raw in items:
                        parsed = parse_component(raw)
                        if parsed and parsed["lcsc"] not in seen_lcsc:
                            if not in_stock_only or parsed["stock"] > 0:
                                results.append(parsed)
                                seen_lcsc.add(parsed["lcsc"])
                else:
                    _record_failure()
                    logger.warning(f"Category search returned HTTP {resp.status_code} for '{query}'")
            except Exception as e:
                _record_failure()
                logger.warning(f"Category search failed ({category}): {e}")

        # Step 2: Generic component search (only if breaker still allows)
        if len(results) < limit and _check_breaker():
            url = f"{JLCSEARCH_BASE}/components/list.json"
            try:
                resp = await client.get(url, params={"search": query, "full": "true"})
                if resp.status_code == 200:
                    _record_success()
                    data = resp.json()
                    items = data if isinstance(data, list) else data.get("components", data.get("results", []))
                    for raw in items:
                        parsed = parse_component(raw)
                        if parsed and parsed["lcsc"] not in seen_lcsc:
                            if not in_stock_only or parsed["stock"] > 0:
                                results.append(parsed)
                                seen_lcsc.add(parsed["lcsc"])
                else:
                    _record_failure()
                    logger.warning(f"Generic LCSC search returned HTTP {resp.status_code} for '{query}'")
            except Exception as e:
                _record_failure()
                logger.warning(f"Generic LCSC search failed: {e}")

    # Sort by: in-stock first, then by stock descending
    results.sort(key=lambda x: (0 if x["stock"] > 100 else 1, -x["stock"]))
    return results[:limit]


async def find_best_match(
    query: str,
    preferred_package: Optional[str] = None,
) -> Optional[dict]:
    """
    Find the single best-matching in-stock component for a search query.
    Optionally prefer a specific package (e.g., '0402', 'SOIC-8').
    """
    results = await search_components(query, limit=20, in_stock_only=False)

    if not results:
        return None

    # Filter to in-stock
    in_stock = [r for r in results if r["stock"] > 100]
    candidates = in_stock if in_stock else results

    # If package preference given, filter
    if preferred_package:
        pkg_lower = preferred_package.lower()
        pkg_matches = [
            r for r in candidates
            if pkg_lower in r["package"].lower()
        ]
        if pkg_matches:
            candidates = pkg_matches

    # Return the highest-stock candidate
    return candidates[0] if candidates else results[0]
