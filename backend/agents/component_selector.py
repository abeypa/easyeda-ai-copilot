"""
Component Selector Agent

Takes the block diagram from the Architect agent and:
1. Uses LLM to decide what real components should implement each block
2. Generates LCSC search queries for each component
3. Searches LCSC to find real part_uuid values
4. Returns a list of BaseComponent objects ready for the Circuit Designer

The LLM outputs a JSON list of components with designators, values, pins,
block_name, and search_query. Then LCSC search resolves the part_uuid.
"""

from __future__ import annotations
import asyncio
import json
import logging
from typing import List, Optional

from llm.provider import LLMProvider, LLMMessage
from models.circuit import BaseComponent, Block, CircuitBlocks, CircuitMetadata, Pin
from lcsc.search import search_components, find_best_match

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an expert electronics engineer with deep knowledge of real electronic components available on LCSC (JLCPCB component library).

## CRITICAL OBEDIENCE — NEVER VIOLATE
- If the user prompt mentions an explicit pin count (e.g. "2-pin spring terminal block", "4-pin header"), the `search_query` MUST contain that exact pin count AND a known LCSC keyword for that pin count (e.g. "KF301-2P 2P" or "2P 5.08mm"). Do NOT substitute a 3-pin or 32-pin variant just because it shares the family name.
- If the user prompt mentions an explicit LCSC part number (e.g. "C2898701", "C75176"), put that C-number AT THE FRONT of `search_query` so the LCSC search locks onto it.
- If the user prompt specifies pin names (ANODE / CATHODE / VCC / GND / SCK / SDA …), use those exact names in the `pins[].name` field. Do NOT relabel them to generic "1" / "2".
- Preserve every component the user listed; do NOT drop or merge any.

Your task is to select REAL, PURCHASABLE components for each block of a circuit design.

## Output Format

Return ONLY valid JSON — a list of components:
```json
[
  {
    "designator": "U1",
    "value": "LM317",
    "block_name": "PowerSupply",
    "search_query": "LM317 LDO voltage regulator TO-220",
    "part_uuid": null,
    "pins": [
      {"pin_number": 1, "name": "ADJ", "signal_name": "ADJ"},
      {"pin_number": 2, "name": "OUT", "signal_name": "VCC_3V3"},
      {"pin_number": 3, "name": "IN", "signal_name": "VIN"}
    ]
  }
]
```

## Component Selection Rules

### Designator Prefixes
- R = Resistor, C = Capacitor, L = Inductor, D = Diode, Q = Transistor (BJT/MOSFET)
- U = IC/Integrated Circuit, J = Connector, X = Crystal/Oscillator
- SW = Switch, F = Fuse, K = Relay, LED = LED (or D for diode)
- Numbering: U1, U2, R1, R2, etc. Sequential, unique across ALL blocks.

### Value Format
- Resistors: "10k", "100R", "4.7M" (no spaces, use k/M/R suffixes)
- Capacitors: "100nF", "10uF", "1pF" (no spaces, use n/u/p suffixes)
- Inductors: "10uH", "100mH"
- ICs/MCUs: Part number only — "LM358", "ATmega328P", "ESP32-WROOM"
- Connectors: "2-pin 2.54mm header"
- LEDs: "Red LED 0603"
- Crystal: "16MHz Crystal"

### Pin Assignment Rules — CRITICAL
1. **Signal names must be consistent**: If resistor R1 pin 2 has signal_name "VCC_3V3", 
   then the capacitor C1 connected to VCC must also have a pin with signal_name "VCC_3V3"
2. **Power nets**: Use standard names: VCC, VCC_3V3, VCC_5V, VIN, GND, VBAT
3. **Signal nets**: Use descriptive names: UART_TX, SDA, SCL, ADC_IN, PWM_OUT, LED_CTRL
4. **NC pins**: Pins not connected should have signal_name "NC"
5. **Every component needs GND**: All ICs and most components need a GND pin

### LCSC-Available Component Examples
- Power: AMS1117-3.3 (LDO 3.3V), MP2307 (buck converter), TP4056 (LiPo charger)
- MCU: STM32F103C8T6, ESP32-WROOM-32, ATmega328P-AU, RP2040
- Op-Amp: LM358, TL072, OPA2134, MCP6002
- Transistor: 2N3904, BC547, IRLZ44N (MOSFET), IRF540N
- Logic: 74HC595, 74HC165, CD4051 (mux), SN74HC04 (inverter)
- Display driver: SSD1306 (OLED), ST7789 (TFT), HD44780 (LCD)
- Sensor interface: ADS1115 (ADC), MCP23017 (I/O expander), PCA9685 (PWM)
- Communication: CH340G (USB-UART), CP2102, W25Q64 (SPI flash)
- Passive: 0402 for resistors/capacitors (good stock, small footprint)

### Component Count Guidelines
- Simple circuit (1-2 blocks): 3-8 components
- Medium circuit (3-5 blocks): 8-25 components  
- Complex circuit (6+ blocks): 15-50 components
- Always include: bypass capacitors (100nF) for each IC power pin, pull-up resistors for I2C
- Include decoupling caps (10uF bulk + 100nF ceramic) on power rails

### Search Query Format for LCSC
- Be specific: "100nF 0402 ceramic capacitor X5R 10V"
- Include package: "LM358 SOIC-8 dual op-amp"
- Include key spec: "10k 0402 resistor 1%"
- For ICs: just the part number: "STM32F103C8T6"
- For CONNECTORS, ALWAYS include explicit pin count and pitch — "2P", "3P", "4P" — and the family identifier when the user gives one. E.g.:
    user: "2-pin 5.08mm spring terminal block"
    search_query: "KF301-2P 2P 5.08mm spring terminal block"
  Without the explicit "2P", LCSC search frequently returns 3-pin or higher variants of the same family — a common source of broken pin-count mismatches in the assembled schematic.
- When the user supplies an LCSC C-number, put it FIRST: "C2898701 KF301-2P 2P 5.08mm spring terminal block".

Return ONLY the JSON array. No explanation, no markdown, no code fences.
"""


async def run_component_selector(
    blocks: CircuitBlocks,
    provider: LLMProvider,
    model: Optional[str] = None,
    resolve_lcsc: bool = True,
) -> List[BaseComponent]:
    """
    Run the Component Selector agent.
    
    Args:
        blocks: Block diagram from the Architect agent
        provider: LLM provider instance
        model: Optional model override
        resolve_lcsc: If True, search LCSC for real part_uuids
    
    Returns:
        List of BaseComponent objects with part_uuid filled in where possible
    """
    # Format blocks for the prompt
    blocks_json = json.dumps({
        "metadata": blocks.metadata.model_dump(),
        "blocks": [b.model_dump() for b in blocks.blocks],
    }, indent=2)

    messages = [
        LLMMessage(role="system", content=SYSTEM_PROMPT),
        LLMMessage(
            role="user",
            content=(
                f"Select components for the following circuit block diagram:\n\n"
                f"```json\n{blocks_json}\n```\n\n"
                f"Design complete component list with proper pin assignments and LCSC search queries."
            ),
        ),
    ]

    logger.info(f"Running component selector for {len(blocks.blocks)} blocks...")

    # Retry up to 2 times if JSON parsing fails
    last_error = None
    for attempt in range(3):
        if attempt > 0:
            logger.info(f"Component selector retry attempt {attempt + 1}/3")
            # On retry, add an explicit reminder about JSON format
            messages_with_hint = messages + [
                LLMMessage(
                    role="user",
                    content=(
                        "IMPORTANT: Your previous response was not valid JSON. "
                        "Return ONLY a JSON array of components. "
                        "Do not include any explanation, markdown fences, or text before/after the JSON. "
                        "Start your response with [ and end with ]."
                    ),
                ),
            ]
        else:
            messages_with_hint = messages

        response = await provider.complete(
            messages=messages_with_hint,
            model=model,
            temperature=0.15 if attempt == 0 else 0.05,
            max_tokens=16384,
        )

        # Parse and validate
        try:
            data = response.extract_json()

            # Handle case where LLM wraps array in an object
            if isinstance(data, dict):
                # Look for the array inside common wrapper keys
                for key in ("components", "result", "data", "items"):
                    if key in data and isinstance(data[key], list):
                        data = data[key]
                        break
                else:
                    raise ValueError("Expected a JSON array of components, got an object")

            if not isinstance(data, list):
                raise ValueError(f"Expected a JSON array of components, got {type(data).__name__}")
            
            components = []
            for i, comp_data in enumerate(data):
                try:
                    # Parse pins
                    pins = [Pin(**p) for p in comp_data.get("pins", [])]
                    comp = BaseComponent(
                        designator=comp_data["designator"],
                        value=comp_data["value"],
                        block_name=comp_data.get("block_name", "Unknown"),
                        search_query=comp_data.get("search_query", comp_data["value"]),
                        part_uuid=comp_data.get("part_uuid"),
                        pins=pins,
                    )
                    components.append(comp)
                except (KeyError, TypeError) as e:
                    logger.warning(f"Skipping invalid component at index {i}: {e}")

            if len(components) == 0:
                raise ValueError("Parsed JSON array but extracted 0 valid components")

            logger.info(f"Component selector produced {len(components)} components")
            last_error = None
            break  # Success

        except (json.JSONDecodeError, ValueError) as e:
            last_error = e
            logger.error(f"Component selector JSON parse error (attempt {attempt + 1}): {e}\nResponse: {response.content[:500]}")
            continue

    if last_error is not None:
        raise ValueError(f"Component selector returned invalid JSON after 3 attempts: {last_error}") from last_error

    # Step 2: Resolve LCSC part UUIDs via search
    if resolve_lcsc and components:
        logger.info("Resolving LCSC part UUIDs...")
        components = await _resolve_lcsc_uuids(components)

    return components


async def _resolve_lcsc_uuids(
    components: List[BaseComponent],
) -> List[BaseComponent]:
    """
    For each component with a search_query, search LCSC and fill in part_uuid.
    If part_uuid is already set (and looks like a raw C-number), convert it to UUID.

    Uses asyncio.gather with a semaphore (max 5 concurrent) for parallel resolution.
    Stops attempting further lookups after 3 consecutive failures.
    """
    sem = asyncio.Semaphore(5)
    failure_count = 0
    max_failures = 3

    async def resolve_one(comp: BaseComponent) -> BaseComponent:
        nonlocal failure_count

        # If too many failures already, skip remaining
        if failure_count >= max_failures:
            return comp

        # If part_uuid already looks like a 32-char hex, keep it
        if comp.part_uuid and len(comp.part_uuid) == 32:
            return comp

        # Search LCSC
        query = comp.search_query or comp.value
        if not query:
            return comp

        async with sem:
            try:
                result = await asyncio.wait_for(find_best_match(query), timeout=5.0)
                if result:
                    comp_data = comp.model_dump()
                    comp_data["part_uuid"] = result["part_uuid"]
                    logger.debug(
                        f"  {comp.designator}: found {result['lcsc_number']} "
                        f"({result['description'][:50]}, stock: {result['stock']})"
                    )
                    return BaseComponent(**comp_data)
                else:
                    logger.debug(f"  {comp.designator}: no LCSC match for '{query}'")
                    return comp
            except (asyncio.TimeoutError, Exception) as e:
                failure_count += 1
                logger.warning(f"LCSC lookup failed for {comp.designator} ({query}): {e}")
                if failure_count >= max_failures:
                    logger.warning(
                        f"LCSC lookup failure threshold ({max_failures}) reached — "
                        "skipping remaining components"
                    )
                return comp

    results = await asyncio.gather(*[resolve_one(c) for c in components])
    return list(results)
