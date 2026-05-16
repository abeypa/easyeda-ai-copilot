"""
EasyEDA AI Copilot — Local FastAPI Backend Server
Port: 5120

Architecture:
  - SSE streaming: POST /v2/chat/s/stream/new → GET /v2/chat/s/stream/{streamId}
  - Non-streaming fallback: POST /v2/chat
  - Model listing: GET /api/models
  - LCSC integration: POST /api/lcsc/search, POST /api/lcsc/stock
  - Health check: GET /api/health

Chat pipeline:
  1. Parse intent from chat history
  2. If circuit request → run Architect → Component Selector → Circuit Designer → ELK Layout
  3. Stream progress via SSE events (status, mes_chunk, think_chunk, message, update-todos, end)
"""

from __future__ import annotations
import asyncio
import json
import logging
import re
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Dict, List, Optional

import httpx
from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

# Local imports
from models.circuit import (
    BaseComponent,
    Block,
    ChatMessage,
    ChatRequest,
    CircuitAssembly,
    CircuitError,
    CircuitStruct,
    LLMSettings,
    LCSCSearchRequest,
    LCSCStockRequest,
)
from models.pcb import PCBPlacementRequest
from llm.factory import get_provider
from lcsc.search import search_components
from lcsc.stock import check_and_replace_components
from agents.architect import run_architect
from agents.component_selector import run_component_selector
from agents.circuit_designer import run_circuit_designer
from agents.pcb_placer import run_pcb_placer
from layout.elk_layout import layout_circuit

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Stream store — in-memory SSE stream state
# ---------------------------------------------------------------------------

class StreamState:
    """
    Tracks the state of a single SSE stream.
    Events are stored so clients can reconnect with last-event-id.
    """
    def __init__(self, stream_id: str, request_body: dict):
        self.stream_id = stream_id
        self.request_body = request_body
        self.events: List[Dict[str, str]] = []  # {"id", "event", "data"}
        self.event_counter = 0
        self.done = False
        self.stopped = False
        self.queue: asyncio.Queue = asyncio.Queue()
        self.created_at = time.time()
        self.task: Optional[asyncio.Task] = None

    def next_event_id(self) -> str:
        self.event_counter += 1
        return str(self.event_counter)

    def put_event(self, event: str, data: str) -> str:
        """Store event and notify waiting clients."""
        event_id = self.next_event_id()
        entry = {"id": event_id, "event": event, "data": data}
        self.events.append(entry)
        self.queue.put_nowait(entry)
        return event_id

    def get_replay_events(self, last_event_id: Optional[str]) -> List[Dict[str, str]]:
        """Return events after last_event_id for SSE reconnection."""
        if last_event_id is None:
            return self.events[:]
        try:
            last_idx = int(last_event_id)
        except (ValueError, TypeError):
            return self.events[:]
        return [e for e in self.events if int(e["id"]) > last_idx]


# Global stream store with cleanup
STREAMS: Dict[str, StreamState] = {}
STREAM_TTL_SECONDS = 3600  # Clean up streams older than 1 hour

# Track the last-used LLM settings so /api/health can report the active model
LAST_LLM_INFO: Dict[str, str] = {"model": "", "provider": ""}


def cleanup_old_streams():
    """Remove completed streams older than TTL."""
    now = time.time()
    to_delete = [
        sid for sid, s in STREAMS.items()
        if s.done and (now - s.created_at) > STREAM_TTL_SECONDS
    ]
    for sid in to_delete:
        del STREAMS[sid]
        logger.debug(f"Cleaned up stream {sid}")


# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("EasyEDA AI Copilot backend starting on port 5120")
    yield
    # Cancel any running stream tasks on shutdown
    for state in STREAMS.values():
        if state.task and not state.task.done():
            state.task.cancel()
    logger.info("Backend shutdown complete")


app = FastAPI(
    title="EasyEDA AI Copilot Backend",
    description="Local AI backend for the EasyEDA AI Copilot extension",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS: allow all origins (extension iframe runs in EasyEDA Pro context)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Intent detection helpers
# ---------------------------------------------------------------------------

# Matches LCSC C-numbers like C2898701, C404270 (5-8 digits after C)
LCSC_NUMBER_RE = re.compile(r'\bC\d{5,8}\b')

# Matches schematic designators: J1, D1, R12, U3, Q2, SW1, LED1, etc.
# CRITICAL: excludes LCSC C-numbers (C + 5-8 digits) which are NOT designators.
# Negative lookahead (?!C\d{5,8}\b) rejects "C21190" but keeps "C1", "C23" (capacitors).
DESIGNATOR_RE = re.compile(r'\b(?!C\d{5,8}\b)([A-Z]{1,3}\d+)\b', re.IGNORECASE)

CIRCUIT_KEYWORDS = [
    "draw", "design", "create", "build", "make", "generate", "circuit", "schematic",
    "diagram", "wiring", "solder", "connect", "assemble", "breadboard", "pcb",
    "нарисуй", "создай", "разработай", "спроектируй",  # Russian
]

COMPONENT_SEARCH_KEYWORDS = [
    "find", "search", "look", "show", "list", "find component",
    "part number", "stock", "available",
]

# Only trigger PCB placement on unambiguous PCB-layout phrases.
# Simple "place" is NOT enough — "place the following components" is circuit intent.
PCB_EXPLICIT_PHRASES = [
    "pcb layout", "pcb placement", "place on pcb", "position on pcb",
    "arrange on pcb", "route pcb", "pcb routing", "board layout",
    "component placement on the board", "place components on the board",
]

EXPLAIN_KEYWORDS = [
    "explain", "what is", "how does", "describe", "analyze", "check", "review",
    "расскажи", "объясни",  # Russian
]


def is_structured_component_list(content: str) -> bool:
    """
    Return True when the message contains a structured component list with at least
    two schematic designators AND at least one LCSC C-number or explicit colon format.

    Recognises formats such as:
      | J1 | DB142V-5.08-4P-GN | 4 | C2898701 |      (table)
      D1: SMDJ26CA TVS, LCSC C2890438, SMA            (colon format)
      pin 1 (Cathode) → VIN_RAW                       (pin assignment)
    """
    # Must have at least 2 designators (J1, D1, R1, etc — NOT LCSC C-numbers)
    designators = DESIGNATOR_RE.findall(content)
    if len(designators) < 2:
        return False

    # Must have at least 1 LCSC C-number OR explicit pin assignment arrows
    lcsc_numbers = LCSC_NUMBER_RE.findall(content)
    has_arrows = '→' in content or '->' in content
    if len(lcsc_numbers) < 1 and not has_arrows:
        return False

    # Must have colon format (D1: ...) OR table format (| D1 | ...) OR explicit pin lines
    has_colon_format = bool(re.search(r'^[A-Z]+\d+\s*:', content, re.IGNORECASE | re.MULTILINE))
    has_table_format = '|' in content and len(lcsc_numbers) >= 1
    has_pin_lines = bool(re.search(r'^pin\s+\d+', content, re.IGNORECASE | re.MULTILINE))

    if has_colon_format or has_table_format or has_pin_lines:
        return True

    return False


def parse_structured_components(content: str) -> List["BaseComponent"]:
    """
    Parse a structured component table from the user message.

    Recognises the markdown-table format:
        | DESIG | VALUE | DESCRIPTION | PIN_COUNT | LCSC_NUMBER |

    The LCSC C-number is stored as `search_query` so the frontend's
    resolveComponentUuids can match by supplierId.
    """
    from models.circuit import BaseComponent, Pin  # local import — avoids circular at module level

    components: List[BaseComponent] = []
    seen: set = set()

    return _parse_structured_components_v2(content)


def _parse_structured_components_v2(content: str) -> List["BaseComponent"]:
    """
    v2.4.2 Complete rewrite — handles direct component specification format:

      D1: SMDJ26CA TVS diode, LCSC C2890438, SMA
      pin 1 (Cathode) → VIN_RAW
      pin 2 (Anode) → GND
      Connect: VIN_PROTECTED → R1 → LED1 anode
      LED1 cathode → GND

    Returns components with correct designators, values, LCSC numbers,
    pin names, and signal connections.
    """
    import re
    from collections import OrderedDict
    from models.circuit import Pin as PinCls

    comp_line_re = re.compile(
        r'^([A-Z]+\d+)\s*:\s*(.+?)(?:\s*,\s*LCSC\s+(C\d{5,8}))?(?:\s*,\s*(.+))?$',
        re.IGNORECASE | re.MULTILINE
    )
    pin_line_re = re.compile(
        r'^pin\s+(\d+)\s*(?:\(([^)]+)\))?\s*→\s*(\S+)',
        re.IGNORECASE | re.MULTILINE
    )

    def detect_pins(val: str, extra: str) -> int:
        text = f"{val} {extra or ''}"
        m = re.search(r'(?:exactly\s+)?(\d+)\s*pins?', text, re.IGNORECASE)
        if m:
            return int(m.group(1))
        m = re.search(r'(\d+)[-\s]pin', text, re.IGNORECASE)
        if m:
            return int(m.group(1))
        if re.search(r'\bSOT-23-3\b', text, re.IGNORECASE):
            return 3
        if re.search(r'\bSOT-23\b', text, re.IGNORECASE):
            return 3
        if re.search(r'\bSOT-23-6\b', text, re.IGNORECASE):
            return 6
        if re.search(r'\bSOIC-8\b', text, re.IGNORECASE):
            return 8
        if re.search(r'\bSOIC-14\b', text, re.IGNORECASE):
            return 14
        return 2

    def default_pin_name(designator: str, pin_num: int, total_pins: int) -> str:
        prefix = re.sub(r'\d+$', '', designator).upper()
        if total_pins > 2:
            return str(pin_num)
        defaults = {
            'R': {1: '1', 2: '2'},
            'C': {1: '+', 2: '-'},
            'L': {1: '1', 2: '2'},
            'D': {1: 'C', 2: 'A'},
            'LED': {1: 'A', 2: 'K'},
            'J': {1: '1', 2: '2'},
            'P': {1: '1', 2: '2'},
            'F': {1: '1', 2: '2'},
        }
        return defaults.get(prefix, {}).get(pin_num, str(pin_num))

    # ── 1. Parse component declarations ──
    comp_map: OrderedDict[str, dict] = OrderedDict()

    # Strategy A: colon format — D1: value, LCSC C12345
    for m in comp_line_re.finditer(content):
        des = m.group(1).upper()
        val = m.group(2).strip()
        lcsc = m.group(3)
        extra = (m.group(4) or '').strip()
        comp_map[des] = {
            'designator': des,
            'value': val,
            'lcsc': lcsc,
            'extra': extra,
            'pins': {},
            'pin_count': detect_pins(val, extra),
        }

    # Strategy B: table format — | R1 | 10k | 2 | C21190 |
    # or: | R1 | 10k | C21190 | (3 columns)
    if not comp_map:
        table_re = re.compile(
            r'\|\s*([A-Z]+\d+)\s*\|\s*([^\|]+?)\s*\|'
            r'(?:\s*(\d+)\s*\|)?'  # optional pin count column
            r'(?:\s*(C\d{5,8})?\s*\|)?',  # optional LCSC column
            re.IGNORECASE,
        )
        for m in table_re.finditer(content):
            des = m.group(1).upper()
            val = m.group(2).strip()
            pin_count_str = m.group(3)
            lcsc = m.group(4)
            if des not in comp_map:
                pcount = int(pin_count_str) if pin_count_str else detect_pins(val, '')
                comp_map[des] = {
                    'designator': des,
                    'value': val,
                    'lcsc': lcsc,
                    'extra': '',
                    'pins': {},
                    'pin_count': pcount,
                }

    # Strategy C: no-colon format — R1 10k resistor, LCSC C21190
    # SAFE: requires "LCSC" keyword so C-numbers are never mistaken for designators
    if not comp_map:
        no_colon_re = re.compile(
            r'^([A-Z]+\d+)\s+([A-Za-z0-9_\(\)\.\-].*?)'
            r'(?:\s*,\s*LCSC\s+(C\d{5,8}))?(?:\s*,\s*(.+))?$',
            re.IGNORECASE | re.MULTILINE,
        )
        for m in no_colon_re.finditer(content):
            des = m.group(1).upper()
            val = m.group(2).strip()
            lcsc = m.group(3)
            extra = (m.group(4) or '').strip()
            # Skip if the "designator" looks like an LCSC number
            if re.match(r'^C\d{5,8}$', des, re.IGNORECASE):
                continue
            if des not in comp_map:
                comp_map[des] = {
                    'designator': des,
                    'value': val,
                    'lcsc': lcsc,
                    'extra': extra,
                    'pins': {},
                    'pin_count': detect_pins(val, extra),
                }

    if not comp_map:
        return []

    # ── 2. Build line-to-component map ──
    lines = content.split('\n')
    line_to_comp: dict[int, str] = {}
    current_comp: str | None = None
    for i, line in enumerate(lines):
        m = comp_line_re.match(line.strip())
        if m:
            current_comp = m.group(1).upper()
        if current_comp and current_comp in comp_map:
            line_to_comp[i] = current_comp

    # ── 3. Parse explicit pin assignment lines ──
    for m in pin_line_re.finditer(content):
        line_idx = content[:m.start()].count('\n')
        comp = line_to_comp.get(line_idx)
        if comp and comp in comp_map:
            pin_num = int(m.group(1))
            pin_name = m.group(2)
            signal = m.group(3)
            comp_map[comp]['pins'][pin_num] = {
                'name': pin_name or default_pin_name(comp, pin_num, comp_map[comp]['pin_count']),
                'signal': signal,
            }

    # ── 4. Parse arrow connection chains ──
    chains: list[list[str]] = []
    for line in lines:
        line = line.strip()
        if '→' not in line:
            continue
        if re.match(r'^pin\s+\d', line, re.IGNORECASE):
            continue  # explicit pin lines already handled
        clean = re.sub(r'^Connect:\s*', '', line, flags=re.IGNORECASE)
        parts = [p.strip() for p in re.split(r'\s*→\s*', clean) if p.strip()]
        if len(parts) >= 2:
            chains.append(parts)

    # ── 5. Process chains with bidirectional signal propagation ──
    chain_assignments: list[tuple[str, str, str]] = []  # (comp, pin_hint, signal)

    for chain in chains:
        # Classify items
        items: list[tuple[str, str, str | None]] = []  # (type, value, hint)
        for item in chain:
            cm = re.match(r'^([A-Z]+\d+)(?:\s+(\w+))?$', item, re.IGNORECASE)
            if cm:
                items.append(('comp', cm.group(1).upper(), (cm.group(2) or '').lower()))
            else:
                items.append(('signal', item, None))

        signal_positions = [i for i, (t, _, _) in enumerate(items) if t == 'signal']
        comp_positions = [i for i, (t, _, _) in enumerate(items) if t == 'comp']

        if not signal_positions or not comp_positions:
            continue

        for ci in comp_positions:
            cname = items[ci][1]
            hint = items[ci][2] or ''
            nearest_sig = None
            nearest_dist = float('inf')
            for si in signal_positions:
                dist = abs(si - ci)
                if dist < nearest_dist and dist > 0:
                    nearest_dist = dist
                    nearest_sig = items[si][1]
            if nearest_sig and cname in comp_map:
                chain_assignments.append((cname, hint, nearest_sig))

    # Apply chain assignments
    for cname, hint, signal in chain_assignments:
        pins = comp_map[cname]['pins']
        pcount = comp_map[cname]['pin_count']

        def _assign(pin_num: int, sig: str) -> None:
            if pin_num not in pins:
                pins[pin_num] = {
                    'name': default_pin_name(cname, pin_num, pcount),
                    'signal': sig,
                }
            elif not pins[pin_num].get('signal') or pins[pin_num]['signal'] == 'NC':
                pins[pin_num]['signal'] = sig

        if hint:
            found = False
            for pn, pdata in pins.items():
                if pdata.get('name', '').lower() == hint:
                    pdata['signal'] = signal
                    found = True
                    break
            if not found:
                for pn in range(1, pcount + 1):
                    if pn not in pins:
                        pins[pn] = {'name': hint.capitalize(), 'signal': signal}
                        break
        else:
            for pn in range(1, pcount + 1):
                if pn not in pins or not pins[pn].get('signal') or pins[pn]['signal'] == 'NC':
                    _assign(pn, signal)
                    break

    # ── 6. Fill missing pins with NC ──
    for comp in comp_map.values():
        for pn in range(1, comp['pin_count'] + 1):
            if pn not in comp['pins']:
                comp['pins'][pn] = {
                    'name': default_pin_name(comp['designator'], pn, comp['pin_count']),
                    'signal': 'NC',
                }

    # ── 7. Build BaseComponent list ──
    components: list[BaseComponent] = []
    for c in comp_map.values():
        pins = [
            PinCls(pin_number=pn, name=pd['name'], signal_name=pd['signal'])
            for pn, pd in sorted(c['pins'].items())
        ]
        # Build search_query: use LCSC if available, else the value
        search_query = c['lcsc'] if c['lcsc'] else c['value']
        components.append(BaseComponent(
            designator=c['designator'],
            value=c['value'],
            block_name='UserDefined',
            search_query=search_query,
            part_uuid=None,
            pins=pins,
        ))

    return components


async def _resolve_structured_component_uuids(
    components: list[BaseComponent],
) -> int:
    """
    Resolve LCSC part UUIDs server-side via jlcsearch.tscircuit.com.

    Strategy (most reliable → least):
    1. If search_query contains an LCSC C-number → deterministic UUID via MD5.
    2. Call find_best_match() on jlcsearch for the search_query.
    3. If no match → generate a deterministic UUID from the designator as fallback.

    Sets both part_uuid and _libraryUuid on each component so the frontend's
    resolveComponentUuids() skips local EasyEDA search entirely.

    Returns the number of successfully resolved components.
    """
    from lcsc.search import find_best_match, lcsc_number_to_part_uuid

    LCSC_RE = re.compile(r'\bC\d{5,8}\b')
    resolved_count = 0

    for comp in components:
        # Skip already resolved
        if comp.part_uuid and len(comp.part_uuid) == 32:
            resolved_count += 1
            continue

        c_numbers = LCSC_RE.findall(comp.search_query or '')

        if c_numbers:
            # Direct C-number → deterministic UUID
            c_num = c_numbers[0].upper()
            comp.part_uuid = lcsc_number_to_part_uuid(c_num)
            comp._libraryUuid = 'lcsc'  # type: ignore[attr-defined]
            resolved_count += 1
            logger.debug(f"Resolved {comp.designator}: C-number {c_num} → UUID")
            continue

        # Try jlcsearch lookup
        try:
            result = await asyncio.wait_for(
                find_best_match(comp.search_query or comp.value),
                timeout=3.0,
            )
            if result:
                comp.part_uuid = result['part_uuid']
                comp._libraryUuid = 'lcsc'  # type: ignore[attr-defined]
                resolved_count += 1
                logger.debug(f"Resolved {comp.designator}: jlcsearch → {result['lcsc_number']}")
                continue
        except Exception:
            pass

        # Fallback: deterministic UUID from designator+value
        # This won't match a real symbol, but the frontend will try generic fallback
        fallback_key = f"{comp.designator}_{comp.value[:20]}"
        comp.part_uuid = lcsc_number_to_part_uuid(fallback_key)
        comp._libraryUuid = 'lcsc'  # type: ignore[attr-defined]
        logger.debug(f"Resolved {comp.designator}: fallback UUID (no LCSC match)")

    return resolved_count


def detect_intent(messages: List[ChatMessage]) -> str:
    """
    Detect user intent from the last human message.

    Returns one of:
        "structured_circuit" \u2014 explicit component list with LCSC C-numbers
        "circuit"            \u2014 natural-language circuit design request
        "component_search"   \u2014 search/find component queries
        "pcb_placement"      \u2014 PCB layout / placement request
        "explain"            \u2014 explanation / analysis request
        "chat"               \u2014 general chat fallback

    Priority (highest first):
        structured_circuit > explain > component_search > pcb_placement > circuit > chat
    """
    last_human = None
    for msg in reversed(messages):
        if msg.role == "human":
            last_human = msg
            break

    if not last_human:
        return "chat"

    content       = last_human.content          # keep original case for C-number detection
    content_lower = content.lower()

    # \u2500\u2500 Structured component list (LCSC C-numbers present) \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    # Must be first: "Place the following components \u2026 C2898701" must NOT fall
    # through to pcb_placement via the word "place".
    if is_structured_component_list(content):
        return "structured_circuit"

    # \u2500\u2500 Explanation / analysis \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    if any(kw in content_lower for kw in EXPLAIN_KEYWORDS):
        return "explain"

    # \u2500\u2500 Component search \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    if any(kw in content_lower for kw in COMPONENT_SEARCH_KEYWORDS):
        return "component_search"

    # \u2500\u2500 PCB layout (strict phrases only) \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    if any(p in content_lower for p in PCB_EXPLICIT_PHRASES):
        return "pcb_placement"

    # \u2500\u2500 Circuit generation: action verb + circuit noun \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    action_verbs = [
        "draw", "design", "create", "build", "make", "generate", "assemble",
        "\u043d\u0430\u0440\u0438\u0441\u0443\u0439", "\u0441\u043e\u0437\u0434\u0430\u0439", "\u0440\u0430\u0437\u0440\u0430\u0431\u043e\u0442\u0430\u0439", "\u0441\u043f\u0440\u043e\u0435\u043a\u0442\u0438\u0440\u0443\u0439",
    ]
    circuit_nouns = ["circuit", "schematic", "diagram", "wiring", "\u0441\u0445\u0435\u043c"]
    has_action = any(v in content_lower for v in action_verbs)
    has_noun   = any(n in content_lower for n in circuit_nouns)
    if has_action and has_noun:
        return "circuit"

    explicit_phrases = [
        "draw circuit", "design circuit", "create circuit", "make circuit",
        "build circuit", "generate circuit", "design schematic", "create schematic",
        "new circuit", "whole circuit",
    ]
    if any(p in content_lower for p in explicit_phrases):
        return "circuit"

    return "chat"


def extract_user_message(messages: List[ChatMessage]) -> str:
    """Extract the last human message content."""
    for msg in reversed(messages):
        if msg.role == "human":
            return msg.content
    return ""


# ---------------------------------------------------------------------------
# SSE helper functions
# ---------------------------------------------------------------------------

def collapse_to_single_block_if_small(circuit: CircuitStruct, threshold: int = 8) -> CircuitStruct:
    """
    v2.4.0 safety net: if the LLM split a small circuit into multiple blocks
    (e.g. 3 LEDs into PowerInput / CurrentLimit / LED), collapse them all
    into a single `UserDefined` block before layout. ELK then produces one
    clean blocks_rect instead of 3 nested boxes that the user has to look at.

    Mirrors the strategy in the architect's CRITICAL BLOCK STRATEGY prompt —
    this is the deterministic fallback for runs where the LLM ignored the
    instruction.
    """
    if not circuit or not circuit.blocks or len(circuit.components) > threshold or len(circuit.blocks) <= 1:
        return circuit

    logger.info(
        f"collapse_to_single_block: merging {len(circuit.blocks)} blocks into 1 "
        f"(component count {len(circuit.components)} <= {threshold})"
    )

    merged_block = Block(
        name="UserDefined",
        description="User-defined simple circuit",
        next_block_names=[],
    )

    # Reassign every component's block_name so layout groups them together.
    new_components = []
    for comp in circuit.components:
        data = comp.model_dump()
        data["block_name"] = "UserDefined"
        new_components.append(type(comp)(**data))

    return CircuitStruct(
        metadata=circuit.metadata,
        blocks=[merged_block],
        components=new_components,
    )


def sse_event(event: str, data: str) -> dict:
    return {"event": event, "data": data}


def make_todo_event(todos: List[dict]) -> str:
    return json.dumps(todos)


def make_message_event(content: str, role: str = "ai") -> str:
    return json.dumps({
        "role": role,
        "content": content,
        "options": {},
        "isReady": True,
    })


def make_circuit_result_message(
    circuit: CircuitAssembly,
    errors: Optional[List[CircuitError]] = None,
    block_diagram: Optional[dict] = None,
) -> str:
    """Format the circuit_agent_result message for the frontend."""
    result = {
        "type": "circuit_agent_result",
        "result": {
            "circuit": circuit.model_dump(),
            "errors": [e.model_dump() for e in (errors or [])],
        }
    }
    if block_diagram:
        result["result"]["blockDiagram"] = block_diagram
    return json.dumps(result, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Pipeline runners
# ---------------------------------------------------------------------------

async def run_circuit_pipeline(
    state: StreamState,
    messages: List[ChatMessage],
    llm_settings: LLMSettings,
) -> None:
    """
    Full circuit generation pipeline:
    1. Architect → block diagram
    2. Component selector → components with LCSC UUIDs
    3. Circuit designer → validated pin connections
    4. Stock check → replace out-of-stock parts
    5. ELK layout → positioned CircuitAssembly
    """
    errors: List[CircuitError] = []

    try:
        provider = get_provider(llm_settings)
    except ValueError as e:
        state.put_event("error", json.dumps({"error": str(e)}))
        state.done = True
        return

    user_message = extract_user_message(messages)

    # -----------------------------------------------------------------------
    # Todos tracker
    # -----------------------------------------------------------------------
    todos = [
        {"status": "in_progress", "content": "Analyzing circuit requirements"},
        {"status": "pending", "content": "Designing block diagram"},
        {"status": "pending", "content": "Selecting components from LCSC"},
        {"status": "pending", "content": "Designing pin connections"},
        {"status": "pending", "content": "Checking component stock"},
        {"status": "pending", "content": "Computing layout"},
    ]

    def update_todo(idx: int, status: str):
        todos[idx]["status"] = status
        state.put_event("update-todos", make_todo_event(todos))

    def complete_todo(idx: int):
        update_todo(idx, "completed")

    def fail_todo(idx: int):
        update_todo(idx, "error")

    state.put_event("update-todos", make_todo_event(todos))

    # -----------------------------------------------------------------------
    # Step 1: Circuit Architect
    # -----------------------------------------------------------------------
    if state.stopped:
        return

    update_todo(0, "completed")
    update_todo(1, "in_progress")
    state.put_event("status", "Designing block diagram...")
    state.put_event("mes_chunk", "I'll design a circuit for you. Analyzing the requirements...\n\n")

    try:
        architect_model = llm_settings.get_model_for_agent("block-diagram")
        blocks = await run_architect(
            description=user_message,
            provider=provider,
            model=architect_model,
            conversation_context=[m.model_dump() for m in messages[:-1]],
        )
        block_names = ", ".join(b.name for b in blocks.blocks)
        state.put_event("mes_chunk", f"**Block diagram designed** ({len(blocks.blocks)} blocks: {block_names})\n\n")
        update_todo(1, "completed")

    except Exception as e:
        logger.error(f"Architect agent failed: {e}")
        errors.append(CircuitError(component="*", error=f"Block diagram design failed: {e}", severity="error"))
        state.put_event("mes_chunk", f"\n**Error in block diagram**: {e}\n")
        fail_todo(1)
        state.put_event("end", "")
        state.done = True
        return

    # -----------------------------------------------------------------------
    # Step 2: Component Selector
    # -----------------------------------------------------------------------
    if state.stopped:
        return

    update_todo(2, "in_progress")
    state.put_event("status", "Selecting components from LCSC...")
    state.put_event("mes_chunk", "Selecting real components from LCSC...\n")

    try:
        component_model = llm_settings.get_model_for_agent("circuit-maker")
        components = await run_component_selector(
            blocks=blocks,
            provider=provider,
            model=component_model,
            resolve_lcsc=True,
        )
        found_lcsc = sum(1 for c in components if c.part_uuid)
        state.put_event("mes_chunk", f"**{len(components)} components selected** ({found_lcsc} with LCSC UUIDs)\n\n")
        update_todo(2, "completed")

    except Exception as e:
        logger.error(f"Component selector failed: {e}")
        errors.append(CircuitError(component="*", error=f"Component selection failed: {e}", severity="error"))
        state.put_event("mes_chunk", f"\n**Error selecting components**: {e}\n")
        fail_todo(2)
        # Continue with empty components list (will produce partial result)
        components = []

    # -----------------------------------------------------------------------
    # Step 3: Circuit Designer
    # -----------------------------------------------------------------------
    if state.stopped:
        return

    update_todo(3, "in_progress")
    state.put_event("status", "Designing pin connections...")
    state.put_event("mes_chunk", "Designing pin connections and validating circuit...\n")

    try:
        designer_model = llm_settings.get_model_for_agent("circuit-maker")
        circuit, design_errors = await run_circuit_designer(
            blocks=blocks,
            components=components,
            provider=provider,
            model=designer_model,
        )
        errors.extend(design_errors)
        
        warning_count = sum(1 for e in design_errors if e.severity == "warning")
        state.put_event(
            "mes_chunk",
            f"**Circuit designed** ({len(circuit.components)} components"
            + (f", {warning_count} warnings" if warning_count else "")
            + ")\n\n"
        )
        update_todo(3, "completed")

    except Exception as e:
        logger.error(f"Circuit designer failed: {e}")
        errors.append(CircuitError(component="*", error=f"Circuit design failed: {e}", severity="error"))
        state.put_event("mes_chunk", f"\n**Error in circuit design**: {e}\n")
        fail_todo(3)
        # Create a minimal circuit struct from the component list
        circuit = CircuitStruct(
            metadata=blocks.metadata,
            blocks=blocks.blocks,
            components=components,
        )

    # -----------------------------------------------------------------------
    # Step 4: Stock check
    # -----------------------------------------------------------------------
    if state.stopped:
        return

    # Check if any component has a resolved 32-char UUID before running stock check
    has_uuids = any(c.part_uuid and len(c.part_uuid) == 32 for c in circuit.components)
    if not has_uuids:
        state.put_event("mes_chunk", "**Skipping stock check** (UUIDs will be resolved client-side)\n\n")
        update_todo(4, "completed")
    else:
        update_todo(4, "in_progress")
        state.put_event("status", "Checking component stock...")
        state.put_event("mes_chunk", "Checking LCSC stock and finding replacements...\n")

        try:
            updated_components, stock_errors = await check_and_replace_components(
                circuit.components,
                min_stock=100,
            )
            errors.extend(stock_errors)
            circuit = CircuitStruct(
                metadata=circuit.metadata,
                blocks=circuit.blocks,
                components=updated_components,
            )
            state.put_event("mes_chunk", f"**Stock check complete**\n\n")
            update_todo(4, "completed")

        except Exception as e:
            logger.warning(f"Stock check failed (non-fatal): {e}")
            errors.append(CircuitError(component="*", error=f"Stock check failed: {e}", severity="warning"))
            update_todo(4, "completed")

    # -----------------------------------------------------------------------
    # Step 5: ELK Layout
    # -----------------------------------------------------------------------
    if state.stopped:
        return

    update_todo(5, "in_progress")
    state.put_event("status", "Computing schematic layout...")
    state.put_event("mes_chunk", "Computing schematic layout...\n\n")

    # v2.4.0 safety net: collapse to one block for small circuits even if
    # the architect ignored the CRITICAL BLOCK STRATEGY prompt.
    pre_collapse_block_count = len(circuit.blocks) if circuit.blocks else 0
    circuit = collapse_to_single_block_if_small(circuit)
    if circuit.blocks and len(circuit.blocks) == 1 and pre_collapse_block_count > 1:
        state.put_event(
            "mes_chunk",
            f"**Merged {pre_collapse_block_count} blocks into 1** "
            f"(small circuit — collapsed for a cleaner schematic)\n\n"
        )

    try:
        assembly = layout_circuit(circuit)
        update_todo(5, "completed")
        state.put_event("mes_chunk", f"**Layout complete** — {len(assembly.components)} components placed, {len(assembly.edges)} connections routed\n\n")

    except Exception as e:
        logger.error(f"Layout failed: {e}")
        errors.append(CircuitError(component="*", error=f"Layout computation failed: {e}", severity="error"))
        fail_todo(5)
        state.put_event("mes_chunk", f"\n**Layout error**: {e}\n")
        state.put_event("end", "")
        state.done = True
        return

    # -----------------------------------------------------------------------
    # Final: Stream the circuit result message
    # -----------------------------------------------------------------------
    if state.stopped:
        return

    # Build the circuit_agent_result payload
    block_diagram_data = {
        "metadata": blocks.metadata.model_dump(),
        "blocks": [b.model_dump() for b in blocks.blocks],
    }

    result_message = make_circuit_result_message(
        circuit=assembly,
        errors=errors,
        block_diagram=block_diagram_data,
    )

    state.put_event("message", make_message_event(result_message))

    # Summary
    info_count = sum(1 for e in errors if e.severity == "info")
    warn_count = sum(1 for e in errors if e.severity == "warning")
    error_count = sum(1 for e in errors if e.severity == "error")

    summary = f"\n---\n**Circuit generation complete!**\n"
    summary += f"- {len(assembly.components)} components placed\n"
    summary += f"- {len(assembly.edges)} connections routed\n"
    if warn_count:
        summary += f"- {warn_count} warnings (check component errors below)\n"
    if error_count:
        summary += f"- {error_count} errors\n"

    state.put_event("mes_chunk", summary)
    state.put_event("end", "")
    state.done = True


async def run_structured_circuit_pipeline(
    state: StreamState,
    messages: List[ChatMessage],
    llm_settings: LLMSettings,
) -> None:
    """
    Shortcut pipeline for messages that already contain an explicit component list
    with LCSC C-numbers.

    Skips the Architect and Component Selector agents — instead it:
      1. Parses components directly from the user message
      2. Creates a minimal synthetic block diagram
      3. Runs the Circuit Designer to assign signal / pin connections
      4. Runs ELK layout
      5. Streams the circuit_agent_result

    The LCSC C-number is stored as `search_query` on each component so the
    frontend's resolveComponentUuids() can look up the part by supplierId.
    """
    from models.circuit import Block, CircuitBlocks, CircuitMetadata, CircuitStruct

    errors: List[CircuitError] = []

    try:
        provider = get_provider(llm_settings)
    except ValueError as e:
        state.put_event("error", json.dumps({"error": str(e)}))
        state.done = True
        return

    user_message = extract_user_message(messages)

    # ── Parse components from the user message ────────────────────────────────
    components = parse_structured_components(user_message)

    if not components:
        # Fallback: run the normal circuit pipeline
        await run_circuit_pipeline(state, messages, llm_settings)
        return

    todos = [
        {"status": "completed",   "content": "Parsing component list"},
        {"status": "in_progress", "content": "Designing pin connections"},
        {"status": "pending",     "content": "Resolving LCSC part UUIDs (client-side)"},
        {"status": "pending",     "content": "Computing layout"},
    ]

    def update_todo(idx: int, status: str):
        todos[idx]["status"] = status
        state.put_event("update-todos", make_todo_event(todos))

    state.put_event("update-todos", make_todo_event(todos))
    state.put_event(
        "mes_chunk",
        f"Found **{len(components)} components** with explicit LCSC part numbers. "
        f"Skipping component selection — designing connections directly...\n\n",
    )

    # ── Build a minimal synthetic block diagram ───────────────────────────────
    blocks = CircuitBlocks(
        metadata=CircuitMetadata(
            project_name="UserDefined Circuit",
            description=f"Circuit assembled from {len(components)} user-specified components",
        ),
        blocks=[
            Block(
                name="UserDefined",
                description="Components specified by the user",
                next_block_names=[],
            )
        ],
    )

    # ── Circuit Designer — assign signal names / pin connections ──────────────
    if state.stopped:
        return

    update_todo(1, "in_progress")
    state.put_event("status", "Designing pin connections...")
    state.put_event("mes_chunk", "Designing signal connections between components...\n")

    try:
        designer_model = llm_settings.get_model_for_agent("circuit-maker")
        circuit, design_errors = await run_circuit_designer(
            blocks=blocks,
            components=components,
            provider=provider,
            model=designer_model,
        )
        errors.extend(design_errors)
        warn_count = sum(1 for e in design_errors if e.severity == "warning")
        state.put_event(
            "mes_chunk",
            f"**Connections designed** ({len(circuit.components)} components"
            + (f", {warn_count} warnings" if warn_count else "")
            + ")\n\n",
        )
        update_todo(1, "completed")
    except Exception as e:
        logger.error(f"Circuit designer failed (structured pipeline): {e}")
        errors.append(CircuitError(component="*", error=f"Circuit design failed: {e}", severity="error"))
        state.put_event("mes_chunk", f"\n**Error in circuit design**: {e}\n")
        todos[1]["status"] = "error"
        state.put_event("update-todos", make_todo_event(todos))
        circuit = CircuitStruct(
            metadata=blocks.metadata,
            blocks=blocks.blocks,
            components=components,
        )

    # ── Resolve LCSC UUIDs server-side via jlcsearch ─────────────────────────
    if state.stopped:
        return

    update_todo(2, "in_progress")
    state.put_event("status", "Resolving LCSC part UUIDs (server-side)...")

    try:
        resolved_count = await _resolve_structured_component_uuids(circuit.components)
        state.put_event(
            "mes_chunk",
            f"**Resolved {resolved_count}/{len(circuit.components)} LCSC UUIDs** via jlcsearch\n\n",
        )
        update_todo(2, "completed")
    except Exception as e:
        logger.warning(f"Server-side LCSC resolution failed: {e}")
        state.put_event("mes_chunk", f"⚠ LCSC resolution failed: {e}\n\n")
        update_todo(2, "error")

    # ── ELK Layout ────────────────────────────────────────────────────────────
    if state.stopped:
        return

    update_todo(3, "in_progress")
    state.put_event("status", "Computing schematic layout...")
    state.put_event("mes_chunk", "Computing schematic layout...\n\n")

    # v2.4.0 safety net: collapse to one block for small explicit-component
    # lists (structured pipeline most often gets exactly this — 3-8 named
    # parts that don't need a multi-block diagram).
    pre_collapse_block_count_s = len(circuit.blocks) if circuit.blocks else 0
    circuit = collapse_to_single_block_if_small(circuit)
    if circuit.blocks and len(circuit.blocks) == 1 and pre_collapse_block_count_s > 1:
        state.put_event(
            "mes_chunk",
            f"**Merged {pre_collapse_block_count_s} blocks into 1** "
            f"(small circuit — collapsed for a cleaner schematic)\n\n"
        )

    try:
        assembly = layout_circuit(circuit)
        update_todo(3, "completed")
        state.put_event(
            "mes_chunk",
            f"**Layout complete** — {len(assembly.components)} components placed, "
            f"{len(assembly.edges)} connections routed\n\n",
        )
    except Exception as e:
        logger.error(f"Layout failed (structured pipeline): {e}")
        errors.append(CircuitError(component="*", error=f"Layout failed: {e}", severity="error"))
        todos[3]["status"] = "error"
        state.put_event("update-todos", make_todo_event(todos))
        state.put_event("mes_chunk", f"\n**Layout error**: {e}\n")
        state.put_event("end", "")
        state.done = True
        return

    # ── Emit result ───────────────────────────────────────────────────────────
    if state.stopped:
        return

    block_diagram_data = {
        "metadata": blocks.metadata.model_dump(),
        "blocks": [b.model_dump() for b in blocks.blocks],
    }
    result_message = make_circuit_result_message(
        circuit=assembly,
        errors=errors,
        block_diagram=block_diagram_data,
    )
    state.put_event("message", make_message_event(result_message))

    warn_count  = sum(1 for e in errors if e.severity == "warning")
    error_count = sum(1 for e in errors if e.severity == "error")

    summary = f"\n---\n**Circuit ready!** ({len(assembly.components)} components, {len(assembly.edges)} connections)"
    if warn_count:
        summary += f"\n- {warn_count} warnings"
    if error_count:
        summary += f"\n- {error_count} errors"
    summary += "\n\nClick **Place Circuit** to insert into EasyEDA. Components will be resolved from LCSC by part number.\n"

    state.put_event("mes_chunk", summary)
    state.put_event("end", "")
    state.done = True


async def run_chat_pipeline(
    state: StreamState,
    messages: List[ChatMessage],
    llm_settings: LLMSettings,
) -> None:
    """Generic chat handler — streams LLM response tokens."""
    try:
        provider = get_provider(llm_settings)
    except ValueError as e:
        state.put_event("error", json.dumps({"error": str(e)}))
        state.done = True
        return

    chat_model = llm_settings.get_model_for_agent("chat")

    # Build message list for the LLM
    from llm.provider import LLMMessage as LMsg
    llm_messages = [
        LMsg(role="system", content=(
            "You are an expert electronics engineer and EDA tool assistant. "
            "You help users design circuits, select components, and use EasyEDA Pro. "
            "Be concise, technical, and helpful. When asked to design a circuit, "
            "guide the user to use the 'Draw Circuit' button for automatic generation."
        )),
    ]

    for msg in messages[-20:]:  # Last 20 messages for context
        role = "user" if msg.role == "human" else "assistant"
        llm_messages.append(LMsg(role=role, content=msg.content))

    state.put_event("status", "Thinking...")

    try:
        async for chunk in provider.stream(
            messages=llm_messages,
            model=chat_model,
            temperature=0.7,
            max_tokens=4096,
        ):
            if state.stopped:
                break
            if chunk:
                state.put_event("mes_chunk", chunk)

        # Mark the message as ready
        state.put_event("end", "")
        state.done = True

    except Exception as e:
        logger.error(f"Chat stream error: {e}")
        state.put_event("mes_chunk", f"\n\n**Error**: {e}")
        state.put_event("end", "")
        state.done = True


async def run_explain_pipeline(
    state: StreamState,
    messages: List[ChatMessage],
    llm_settings: LLMSettings,
) -> None:
    """Circuit explanation handler."""
    try:
        provider = get_provider(llm_settings)
    except ValueError as e:
        state.put_event("error", json.dumps({"error": str(e)}))
        state.done = True
        return

    model = llm_settings.get_model_for_agent("circuit-explainer")

    from llm.provider import LLMMessage as LMsg
    llm_messages = [
        LMsg(role="system", content=(
            "You are an expert electronics engineer. Analyze circuit designs, "
            "explain component functions, identify potential issues, and suggest improvements. "
            "Be thorough but concise. Use markdown formatting."
        )),
    ]

    for msg in messages[-10:]:
        role = "user" if msg.role == "human" else "assistant"
        content = msg.content
        # Strip circuit_agent_result JSON for context to save tokens
        if "circuit_agent_result" in content:
            try:
                parsed = json.loads(content)
                if parsed.get("type") == "circuit_agent_result":
                    content = f"[Circuit with {len(parsed.get('result', {}).get('circuit', {}).get('components', []))} components]"
            except Exception:
                pass
        llm_messages.append(LMsg(role=role, content=content))

    state.put_event("status", "Analyzing circuit...")

    try:
        async for chunk in provider.stream(
            messages=llm_messages,
            model=model,
            temperature=0.3,
            max_tokens=4096,
        ):
            if state.stopped:
                break
            if chunk:
                state.put_event("mes_chunk", chunk)

        state.put_event("end", "")
        state.done = True

    except Exception as e:
        logger.error(f"Explain pipeline error: {e}")
        state.put_event("mes_chunk", f"\n\n**Error**: {e}")
        state.put_event("end", "")
        state.done = True


async def run_stream_pipeline(state: StreamState) -> None:
    """
    Main dispatch: parse request, detect intent, run appropriate pipeline.
    """
    try:
        body = state.request_body
        context = body.get("context", [])
        llm_settings_raw = body.get("llmSettings", {})

        # Parse messages and settings
        messages = [ChatMessage(**m) for m in context]
        llm_settings = LLMSettings(**llm_settings_raw)

        # Track model info for health endpoint
        LAST_LLM_INFO["provider"] = llm_settings.provider or ""
        base_model = llm_settings.get_model_for_agent("chat")
        LAST_LLM_INFO["model"] = base_model

        # Detect intent
        intent = detect_intent(messages)
        logger.info(f"Stream {state.stream_id}: detected intent '{intent}'")

        if intent == "structured_circuit":
            await run_structured_circuit_pipeline(state, messages, llm_settings)
        elif intent == "circuit":
            await run_circuit_pipeline(state, messages, llm_settings)
        elif intent == "explain":
            await run_explain_pipeline(state, messages, llm_settings)
        else:
            # Default: general chat (covers "chat", "component_search", "pcb_placement")
            await run_chat_pipeline(state, messages, llm_settings)

    except Exception as e:
        logger.error(f"Stream pipeline error: {e}", exc_info=True)
        state.put_event("error", json.dumps({"error": str(e)}))
        state.put_event("end", "")
        state.done = True


# ---------------------------------------------------------------------------
# SSE streaming endpoints
# ---------------------------------------------------------------------------

@app.post("/v2/chat/s/stream/new")
async def create_stream(request: Request):
    """
    Create a new SSE stream.
    The client POSTs the full request body here, gets back a streamId,
    then connects to GET /v2/chat/s/stream/{streamId} for the event stream.
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    stream_id = str(uuid.uuid4())
    state = StreamState(stream_id=stream_id, request_body=body)
    STREAMS[stream_id] = state

    # Start the pipeline in the background
    task = asyncio.create_task(run_stream_pipeline(state))
    state.task = task

    cleanup_old_streams()

    logger.info(f"Created stream {stream_id}")
    return JSONResponse({"streamId": stream_id})


@app.get("/v2/chat/s/stream/{stream_id}")
async def get_stream(
    stream_id: str,
    last_event_id: Optional[str] = Query(None, alias="last-event-id"),
):
    """
    SSE event stream endpoint.
    Supports reconnection via ?last-event-id= parameter.
    """
    state = STREAMS.get(stream_id)
    if not state:
        raise HTTPException(status_code=404, detail=f"Stream {stream_id} not found")

    async def event_generator() -> AsyncIterator[dict]:
        # Replay missed events on reconnection
        if last_event_id:
            missed = state.get_replay_events(last_event_id)
            for event in missed:
                yield {
                    "id": event["id"],
                    "event": event["event"],
                    "data": event["data"],
                }

        # Stream new events
        while not (state.done and state.queue.empty()):
            try:
                event = await asyncio.wait_for(state.queue.get(), timeout=1.0)
                yield {
                    "id": event["id"],
                    "event": event["event"],
                    "data": event["data"],
                }
                if event["event"] == "end":
                    break
            except asyncio.TimeoutError:
                # Send keepalive comment
                if state.done and state.queue.empty():
                    break
                yield {"event": "ping", "data": ""}
            except asyncio.CancelledError:
                break

    return EventSourceResponse(event_generator())


@app.post("/v2/chat/s/stream/{stream_id}/stop")
async def stop_stream(stream_id: str):
    """Stop a running SSE stream."""
    state = STREAMS.get(stream_id)
    if not state:
        return JSONResponse({"ok": True, "message": "Stream not found (may have already ended)"})

    state.stopped = True
    if state.task and not state.task.done():
        state.task.cancel()

    state.put_event("end", "")
    state.done = True

    logger.info(f"Stopped stream {stream_id}")
    return JSONResponse({"ok": True})


# ---------------------------------------------------------------------------
# Non-streaming chat fallback (/v2/chat with task polling pattern)
# ---------------------------------------------------------------------------

# Task store for the polling-based /v2/chat endpoint
TASKS: Dict[str, dict] = {}


@app.post("/v2/chat/start")
async def chat_start(request: Request):
    """Start a non-streaming chat operation (polling pattern)."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    operation_id = str(uuid.uuid4())
    TASKS[operation_id] = {
        "status": "pending",
        "result": None,
        "error": None,
        "intermediateResult": {"action": "Processing..."},
    }

    async def run_task():
        try:
            context = body.get("context", [])
            llm_settings_raw = body.get("llmSettings", {})
            messages = [ChatMessage(**m) for m in context]
            llm_settings = LLMSettings(**llm_settings_raw)

            TASKS[operation_id]["status"] = "running"
            TASKS[operation_id]["intermediateResult"] = {"action": "Detecting intent..."}

            provider = get_provider(llm_settings)
            intent = detect_intent(messages)
            user_msg = extract_user_message(messages)

            TASKS[operation_id]["intermediateResult"] = {"action": f"Running {intent} pipeline..."}

            if intent == "circuit":
                # Run full pipeline (non-streaming)
                from llm.provider import LLMMessage as LMsg
                architect_model = llm_settings.get_model_for_agent("block-diagram")
                blocks = await run_architect(user_msg, provider, architect_model)

                TASKS[operation_id]["intermediateResult"] = {"action": "Selecting components..."}
                components = await run_component_selector(blocks, provider,
                    llm_settings.get_model_for_agent("circuit-maker"))

                TASKS[operation_id]["intermediateResult"] = {"action": "Designing circuit..."}
                circuit, errors = await run_circuit_designer(blocks, components, provider,
                    llm_settings.get_model_for_agent("circuit-maker"))

                TASKS[operation_id]["intermediateResult"] = {"action": "Computing layout..."}
                circuit = collapse_to_single_block_if_small(circuit)
                assembly = layout_circuit(circuit)

                result_content = make_circuit_result_message(assembly, errors)
                TASKS[operation_id]["result"] = {
                    "returnMessages": [
                        {"role": "ai", "content": result_content, "options": {}, "isReady": True}
                    ]
                }
            else:
                # Simple chat
                from llm.provider import LLMMessage as LMsg
                llm_messages = [
                    LMsg(role="system", content="You are an expert electronics engineer assistant."),
                ]
                for msg in messages[-10:]:
                    role = "user" if msg.role == "human" else "assistant"
                    llm_messages.append(LMsg(role=role, content=msg.content))

                response = await provider.complete(llm_messages,
                    model=llm_settings.get_model_for_agent("chat"), temperature=0.7)

                TASKS[operation_id]["result"] = {
                    "returnMessages": [
                        {"role": "ai", "content": response.content, "options": {}, "isReady": True}
                    ]
                }

            TASKS[operation_id]["status"] = "completed"

        except Exception as e:
            logger.error(f"Task {operation_id} failed: {e}", exc_info=True)
            TASKS[operation_id]["status"] = "failed"
            TASKS[operation_id]["error"] = str(e)

    asyncio.create_task(run_task())
    return JSONResponse({"operationId": operation_id})


@app.get("/v2/chat/status/{operation_id}")
async def chat_status(operation_id: str):
    """Poll status of a non-streaming chat operation."""
    task = TASKS.get(operation_id)
    if not task:
        raise HTTPException(status_code=404, detail="Operation not found")
    return JSONResponse(task)


@app.get("/v2/chat/cancel/{operation_id}")
async def chat_cancel(operation_id: str):
    """Cancel a non-streaming chat operation."""
    task = TASKS.get(operation_id)
    if task:
        task["status"] = "failed"
        task["error"] = "Cancelled by user"
    return JSONResponse({"ok": True})


@app.post("/v2/chat")
async def chat_direct(request: Request):
    """
    Simple synchronous chat endpoint (for very basic clients).
    Waits for the full response before returning.
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    try:
        context = body.get("context", [])
        llm_settings_raw = body.get("llmSettings", {})
        messages = [ChatMessage(**m) for m in context]
        llm_settings = LLMSettings(**llm_settings_raw)

        provider = get_provider(llm_settings)
        intent = detect_intent(messages)
        user_msg = extract_user_message(messages)

        if intent == "circuit":
            architect_model = llm_settings.get_model_for_agent("block-diagram")
            blocks = await run_architect(user_msg, provider, architect_model)
            components = await run_component_selector(blocks, provider,
                llm_settings.get_model_for_agent("circuit-maker"))
            circuit, errors = await run_circuit_designer(blocks, components, provider,
                llm_settings.get_model_for_agent("circuit-maker"))
            circuit = collapse_to_single_block_if_small(circuit)
            assembly = layout_circuit(circuit)
            result_content = make_circuit_result_message(assembly, errors)
            return JSONResponse({
                "returnMessages": [
                    {"role": "ai", "content": result_content, "options": {}, "isReady": True}
                ]
            })
        else:
            from llm.provider import LLMMessage as LMsg
            llm_messages = [
                LMsg(role="system", content="You are an expert electronics engineer assistant."),
            ]
            for msg in messages[-10:]:
                role = "user" if msg.role == "human" else "assistant"
                llm_messages.append(LMsg(role=role, content=msg.content))
            response = await provider.complete(llm_messages,
                model=llm_settings.get_model_for_agent("chat"), temperature=0.7)
            return JSONResponse({
                "returnMessages": [
                    {"role": "ai", "content": response.content, "options": {}, "isReady": True}
                ]
            })

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Direct chat error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Model listing endpoint
# ---------------------------------------------------------------------------

class ModelListRequest(BaseModel):
    llmSettings: dict


@app.get("/api/models")
async def list_models(request: Request):
    """
    List available models for the configured LLM provider.
    Reads llmSettings from query params or Authorization header (simplified).
    """
    # Try to get llmSettings from body if POST, or return default list
    try:
        body = await request.json()
        llm_settings = LLMSettings(**body.get("llmSettings", {}))
        provider = get_provider(llm_settings)
        models = await provider.list_models()
        return JSONResponse({"models": models})
    except Exception as e:
        logger.warning(f"Model listing error: {e}")
        # Return a safe default list
        return JSONResponse({
            "models": [
                {"id": "gpt-4o", "name": "GPT-4o", "provider": "openai"},
                {"id": "gpt-4o-mini", "name": "GPT-4o Mini", "provider": "openai"},
                {"id": "claude-3-5-sonnet-latest", "name": "Claude 3.5 Sonnet", "provider": "anthropic"},
            ],
            "error": str(e) if e else None
        })


@app.post("/api/models")
async def list_models_post(body: dict):
    """POST version of model listing (for frontend compatibility)."""
    try:
        llm_settings = LLMSettings(**body.get("llmSettings", {}))
        provider = get_provider(llm_settings)
        models = await provider.list_models()
        return JSONResponse({"models": models})
    except Exception as e:
        logger.warning(f"Model listing error: {e}")
        return JSONResponse({"models": [], "error": str(e)})


# ---------------------------------------------------------------------------
# LCSC endpoints
# ---------------------------------------------------------------------------

@app.post("/api/lcsc/search")
async def lcsc_search(req: LCSCSearchRequest):
    """Search LCSC components via jlcsearch.tscircuit.com."""
    try:
        results = await search_components(
            query=req.query,
            limit=req.limit,
            in_stock_only=False,
        )
        return JSONResponse({"results": results, "query": req.query})
    except Exception as e:
        logger.error(f"LCSC search error: {e}")
        raise HTTPException(status_code=500, detail=f"LCSC search failed: {e}")


@app.post("/api/lcsc/stock")
async def lcsc_stock(req: LCSCStockRequest):
    """
    Check stock for a list of components and find equivalents for out-of-stock parts.
    """
    try:
        updated, errors = await check_and_replace_components(
            components=req.components,
            min_stock=req.min_stock,
        )
        return JSONResponse({
            "components": [c.model_dump() for c in updated],
            "errors": [e.model_dump() for e in errors],
        })
    except Exception as e:
        logger.error(f"LCSC stock check error: {e}")
        raise HTTPException(status_code=500, detail=f"Stock check failed: {e}")


# ---------------------------------------------------------------------------
# PCB placement endpoint
# ---------------------------------------------------------------------------

@app.post("/api/pcb/place")
async def pcb_place(request: Request):
    """Run PCB component placement via LLM agent."""
    try:
        body = await request.json()
        llm_settings = LLMSettings(**body.get("llmSettings", {}))
        placement_req = PCBPlacementRequest(**body.get("placement", body))
        provider = get_provider(llm_settings)
        result = await run_pcb_placer(placement_req, provider)
        return JSONResponse(result.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"PCB placement error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/api/health")
async def health_check(request: Request):
    """
    Health check endpoint.
    Returns server status, active stream count, and current LLM model/provider.
    Accepts optional query params: ?provider=...&model=... to report ad-hoc,
    or reads from the last stream session.
    """
    active_streams = sum(1 for s in STREAMS.values() if not s.done)

    # Allow frontend to POST or pass query params for model info
    provider = request.query_params.get("provider", "") or LAST_LLM_INFO.get("provider", "")
    model = request.query_params.get("model", "") or LAST_LLM_INFO.get("model", "")

    return JSONResponse({
        "status": "ok",
        "version": "2.0.0",
        "active_streams": active_streams,
        "server": "EasyEDA AI Copilot Backend",
        "port": 5120,
        "model": model,
        "provider": provider,
    })


@app.post("/api/health")
async def health_check_post(request: Request):
    """
    POST version of health check — the frontend can send llmSettings
    so we can report the active model/provider immediately.
    """
    active_streams = sum(1 for s in STREAMS.values() if not s.done)
    provider = ""
    model = ""

    try:
        body = await request.json()
        llm_raw = body.get("llmSettings", {})
        if llm_raw:
            llm_settings = LLMSettings(**llm_raw)
            provider = llm_settings.provider or ""
            model = llm_settings.get_model_for_agent("chat")
            LAST_LLM_INFO["provider"] = provider
            LAST_LLM_INFO["model"] = model
    except Exception:
        pass

    return JSONResponse({
        "status": "ok",
        "version": "2.0.0",
        "active_streams": active_streams,
        "server": "EasyEDA AI Copilot Backend",
        "port": 5120,
        "model": model,
        "provider": provider,
    })


@app.get("/")
async def root():
    return JSONResponse({
        "message": "EasyEDA AI Copilot Backend",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/api/health",
    })


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=5120,
        reload=True,
        log_level="info",
    )
