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
- The `value` field must be a concise human-readable identifier (e.g. "10k", "100nF", "LED RED 0603", "2-pin spring terminal"). Do NOT put the LCSC C-number here.

## Output Format

Return ONLY valid JSON — a list of components:
```json
[
  {
    "designator": "U1",
    "value": "LM358",
    "block_name": "Amplifier",
    "search_query": "LM358 SOIC-8 dual op-amp",
    "part_uuid": null,
    "pins": [
      {"pin_number": 1, "name": "OUT1", "signal_name": "AMP_OUT"},
      {"pin_number": 2, "name": "IN1-", "signal_name": "FEEDBACK_1"},
      {"pin_number": 3, "name": "IN1+", "signal_name": "SIG_IN"},
      {"pin_number": 4, "name": "GND", "signal_name": "GND"},
      {"pin_number": 8, "name": "VCC", "signal_name": "VCC_5V"}
    ]
  }
]
```

## Designator Prefixes
- R = Resistor, C = Capacitor, L = Inductor, D = Diode, Q = Transistor (BJT/MOSFET)
- U = IC/Integrated Circuit, J = Connector, X = Crystal/Oscillator
- SW = Switch, F = Fuse, K = Relay, LED = LED (or D for diode)
- Numbering: U1, U2, R1, R2, etc. Sequential, unique across ALL blocks.

## Value Format
- Resistors: "10k", "100R", "4.7M" (no spaces, use k/M/R suffixes)
- Capacitors: "100nF", "10uF", "1pF" (no spaces, use n/u/p suffixes)
- Inductors: "10uH", "100mH"
- ICs/MCUs: Part number only — "LM358", "ATmega328P", "ESP32-WROOM"
- Connectors: "2-pin 2.54mm header", "4-pin spring terminal 5.08mm"
- LEDs: "Red LED 0603", "Green LED 0805"
- Crystal: "16MHz Crystal"

## Pin Assignment Rules — CRITICAL
1. **Signal names must be consistent**: If resistor R1 pin 2 has signal_name "VCC_3V3",
   then the capacitor C1 connected to VCC must also have a pin with signal_name "VCC_3V3"
2. **Power nets**: Use standard names: GND, VCC_3V3, VCC_5V, VIN, VBAT, VDD
3. **Signal nets**: Use descriptive names: UART_TX, SDA, SCL, ADC_IN, PWM_OUT, LED_CTRL
4. **NC pins**: Pins not connected should have signal_name "NC"
5. **Every IC needs GND**: All ICs and most components need a GND pin connection
6. **Every IC needs power**: All ICs need a VCC/VDD pin connection
7. **Bypass capacitors**: For every IC power pin, include a 100nF ceramic capacitor between VCC and GND

## Component Selection by Category

### Passives (always include when needed)
- Resistors: 0402 or 0603. 1% tolerance standard. "10k 0402 resistor 1%"
- Capacitors: 0402 or 0603. X5R/X7R ceramic. "100nF 0402 ceramic capacitor X5R 10V", "10uF 0603 ceramic X5R 10V"
- Inductors: "10uH 0805 inductor", "100uH SMD inductor"

### Power ICs
- LDO 3.3V: AMS1117-3.3, XC6206P332MR, ME6211C33M5G
- LDO 5V: AMS1117-5.0, XC6206P502MR
- Buck: MP2307, MP1584EN, TPS5430
- LiPo charger: TP4056, MCP73831

### Microcontrollers
- STM32: STM32F103C8T6 (C8T6 = 48-pin LQFP), STM32F401CCU6
- ESP32: ESP32-WROOM-32, ESP32-S3-WROOM-1
- Arduino: ATmega328P-AU (TQFP), ATmega2560-16AU
- Raspberry Pi: RP2040 (QFN-56)

### Op-Amps
- General purpose: LM358 (SOIC-8), LM324 (SOIC-14), MCP6002
- Precision: TL072, OPA2134, MCP6022
- Rail-to-rail: MCP6002, LMV358

### Transistors
- BJT NPN: 2N3904 (TO-92, SOT-23), BC547, MMBT2222A
- BJT PNP: 2N3906, BC557
- MOSFET N-ch: IRLZ44N (logic level), AO3400, SI2302
- MOSFET P-ch: AO3401, SI2301

### Diodes
- General: 1N4148W (SOD-123), 1N4007 (SMA)
- Schottky: SS34 (SMA), BAT54C (SOT-23)
- Zener: BZT52C3V3 (SOD-123), BZT52C5V1
- LED: Various colors in 0402, 0603, 0805

### Connectors — CRITICAL: always specify pin count
- Headers: "2.54mm header 2P", "2.54mm header 4P", "2.54mm header 10P"
- Spring terminals: "KF301-2P 2P 5.08mm spring terminal", "KF301-3P 3P 5.08mm"
- USB: "USB Type-C 16P", "Micro USB 5P"
- JST: "JST XH 2.54mm 2P", "JST PH 2.0mm 3P"

### Communication
- USB-UART: CH340G (SOIC-16), CH340C, CP2102 (QFN-28)
- CAN: TJA1051T (SOIC-8), MCP2551
- Ethernet: W5500 (LQFP-48), LAN8720
- RS-485: MAX485 (SOIC-8), SP3485EN

### Memory
- SPI Flash: W25Q64JVSSIQ (SOIC-8), W25Q128JVSIQ
- EEPROM: 24C02 (SOT-23-5), 24C256 (SOIC-8)
- SRAM: 23K256 (SOIC-8)

### Sensors / Interfaces
- ADC: ADS1115 (MSOP-10), MCP3008 (SOIC-16)
- DAC: MCP4725 (SOT-23-6)
- I/O expander: MCP23017 (SOIC-28), PCF8574 (SOIC-16)
- Temperature: DS18B20 (TO-92), TMP36 (SOT-23)

## Search Query Format for LCSC — CRITICAL
- Be specific: "100nF 0402 ceramic capacitor X5R 10V"
- Include package: "LM358 SOIC-8 dual op-amp"
- Include key spec: "10k 0402 resistor 1%"
- For ICs: just the part number: "STM32F103C8T6"
- For CONNECTORS, ALWAYS include explicit pin count and pitch:
    user: "2-pin 5.08mm spring terminal block"
    search_query: "KF301-2P 2P 5.08mm spring terminal block"
  Without the explicit "2P", LCSC search frequently returns 3-pin or higher variants — a common source of broken pin-count mismatches.
- When the user supplies an LCSC C-number, put it FIRST: "C2898701 KF301-2P 2P 5.08mm spring terminal block".
- For resistors/capacitors: include size + value + type: "10k 0402 resistor 1%", "100nF 0402 ceramic capacitor X5R 10V"

## Component Count Guidelines
- Simple circuit (1-2 blocks): 3-8 components
- Medium circuit (3-5 blocks): 8-25 components
- Complex circuit (6+ blocks): 15-50 components
- Always include: bypass capacitors (100nF) for each IC power pin, pull-up resistors for I2C (4.7k typical)
- Include decoupling: 10uF bulk + 100nF ceramic on power rails

## Bypass Capacitor Rule (MANDATORY)
For EVERY IC in the design, add ONE 100nF ceramic capacitor:
- Place its "+" pin on the same VCC net as the IC's VCC pin
- Place its "-" pin on GND
- Designator: C1, C2, etc. (sequential with other capacitors)

## Pull-Up Resistor Rule (for I2C, open-drain lines)
For I2C buses (SDA, SCL), add 4.7k pull-up resistors to VCC_3V3 or VCC_5V.

Return ONLY the JSON array. No explanation, no markdown, no code fences. Start with [ and end with ].
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
                f"Design complete component list with proper pin assignments and LCSC search queries. "
                f"Remember: every IC needs a 100nF bypass capacitor. I2C lines need 4.7k pull-ups. "
                f"Connectors MUST include exact pin count in search_query."
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
