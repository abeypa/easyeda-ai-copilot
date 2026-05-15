"""
Circuit Designer Agent

Takes the block diagram + component list and produces a complete circuit:
  - Validates and refines pin assignments
  - Ensures all signal names are consistent across components
  - Checks for missing connections (floating pins)
  - Returns a complete CircuitStruct

This agent is the most detail-oriented — it reviews every pin connection
and resolves any inconsistencies in signal naming.
"""

from __future__ import annotations
import json
import logging
from collections import defaultdict
from typing import Dict, List, Optional, Set, Tuple

from llm.provider import LLMProvider, LLMMessage
from models.circuit import (
    BaseComponent,
    Block,
    CircuitBlocks,
    CircuitMetadata,
    CircuitStruct,
    Pin,
    CircuitError,
)

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a senior electronics design engineer. Your task is to review and finalize a circuit's pin connections.

You will receive:
1. A block diagram (blocks with descriptions)
2. A component list with initial pin assignments

Your job is to OUTPUT the FINAL, CORRECTED component list with validated pin connections.

## Output Format

Return ONLY valid JSON — the same structure as the input components list, but with corrected pin signal_names:
```json
[
  {
    "designator": "U1",
    "value": "LM358",
    "block_name": "Amplifier",
    "search_query": "LM358 SOIC-8",
    "part_uuid": "existing_uuid_or_null",
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

## Pin Connection Rules — CRITICAL

### Signal Name Consistency
- **IDENTICAL signal names = electrically connected**
- If R1 pin 2 = "VCC_3V3", then U1 VCC = "VCC_3V3" (not "VCC" or "3V3")
- If U1 OUT = "UART_TX", then J1 pin 3 = "UART_TX"
- Power nets: use EXACTLY one of: GND, VCC, VCC_3V3, VCC_5V, VCC_12V, VIN, VBAT

### Required Connections
1. **Every IC needs**: VCC (or supply) and GND connected
2. **Every IC needs bypass caps**: 100nF capacitor between VCC pin and GND
3. **I2C buses**: SDA must go to all I2C devices, SCL must go to all I2C devices
4. **UART**: TX of master → RX of slave, RX of master → TX of slave (crossed)
5. **Power rails**: Voltage regulator OUT → all component VCC pins of that voltage

### Common Pin Names by Component Type
- Op-Amps: IN+, IN-, OUT, V+, V- (or VCC/GND)
- LDO regulators: IN (or VIN), OUT (or VOUT), GND, ADJ
- MOSFETs: G (Gate), S (Source), D (Drain)
- BJTs: B (Base), C (Collector), E (Emitter)
- MCUs: VCC/VDD, GND/VSS, digital pins by function (UART_TX, SDA, SCL, etc.)
- Capacitors: pin 1 (+), pin 2 (-)
- Resistors: pin 1, pin 2
- LEDs: A (Anode = +), K or C (Cathode = -)
- Crystal: pin 1, pin 2 (or XIN, XOUT)

### Floating Pins
- Unused IC inputs: connect to GND or VCC via pull-up/pull-down (do NOT leave floating)
- MOSFET gates: always have a pull-down resistor to GND
- Op-amp inputs: never leave floating
- "NC" is acceptable only for truly unused IC pins per datasheet

### Design Verification Checklist
□ Every component has GND connection
□ Every IC has VCC/power connection
□ Signal names exactly match between connected components
□ No signal name appears only once (except power rails like GND, VCC)
□ I2C: SDA and SCL connected to all I2C devices + pull-up resistors
□ UART: TX/RX correctly crossed between master and slave

Return ONLY the JSON array of components. No explanation, no markdown.
"""


async def run_circuit_designer(
    blocks: CircuitBlocks,
    components: List[BaseComponent],
    provider: LLMProvider,
    model: Optional[str] = None,
) -> Tuple[CircuitStruct, List[CircuitError]]:
    """
    Run the Circuit Designer agent to validate and finalize pin connections.
    
    Returns (CircuitStruct, errors)
    """
    blocks_json = json.dumps([b.model_dump() for b in blocks.blocks], indent=2)
    components_json = json.dumps([c.model_dump() for c in components], indent=2)

    messages = [
        LLMMessage(role="system", content=SYSTEM_PROMPT),
        LLMMessage(
            role="user",
            content=(
                f"Block diagram:\n```json\n{blocks_json}\n```\n\n"
                f"Components with initial pin assignments:\n```json\n{components_json}\n```\n\n"
                f"Review all pin connections, fix signal name inconsistencies, "
                f"ensure all required connections are present, and return the corrected component list."
            ),
        ),
    ]

    logger.info(f"Running circuit designer for {len(components)} components...")

    # Retry up to 2 times on parse failure
    last_error = None
    data = None
    for attempt in range(3):
        if attempt > 0:
            logger.info(f"Circuit designer retry attempt {attempt + 1}/3")
            retry_messages = messages + [
                LLMMessage(
                    role="user",
                    content=(
                        "IMPORTANT: Your previous response was not valid JSON. "
                        "Return ONLY a JSON array of components. "
                        "No explanation, no markdown. Start with [ and end with ]."
                    ),
                ),
            ]
        else:
            retry_messages = messages

        response = await provider.complete(
            messages=retry_messages,
            model=model,
            temperature=0.1 if attempt == 0 else 0.02,
            max_tokens=16384,
        )

        try:
            data = response.extract_json()

            # Handle dict wrapper
            if isinstance(data, dict):
                for key in ("components", "result", "data", "items"):
                    if key in data and isinstance(data[key], list):
                        data = data[key]
                        break
                else:
                    raise ValueError("Expected a JSON array")

            if not isinstance(data, list):
                raise ValueError(f"Expected a JSON array, got {type(data).__name__}")
            last_error = None
            break
        except (json.JSONDecodeError, ValueError) as e:
            last_error = e
            logger.error(f"Circuit designer JSON parse error (attempt {attempt + 1}): {e}")
            continue

    # Parse and validate
    errors: List[CircuitError] = []
    if last_error is not None or data is None:
        # Fall back to original components
        errors.append(CircuitError(
            component="*",
            error=f"Circuit designer returned invalid response after 3 attempts: {last_error}. Using original component list.",
            severity="warning",
        ))
        circuit = CircuitStruct(
            metadata=blocks.metadata,
            blocks=blocks.blocks,
            components=components,
        )
        return circuit, errors

    try:
        if not isinstance(data, list):
            raise ValueError("Expected a JSON array")

        updated_components = []
        for comp_data in data:
            try:
                pins = [Pin(**p) for p in comp_data.get("pins", [])]
                comp = BaseComponent(
                    designator=comp_data["designator"],
                    value=comp_data["value"],
                    block_name=comp_data.get("block_name", "Unknown"),
                    search_query=comp_data.get("search_query", comp_data["value"]),
                    part_uuid=comp_data.get("part_uuid"),
                    pins=pins,
                )
                updated_components.append(comp)
            except (KeyError, TypeError) as e:
                logger.warning(f"Skipping invalid component: {e}")
                errors.append(CircuitError(
                    component=comp_data.get("designator", "unknown"),
                    error=f"Invalid component data: {e}",
                    severity="warning",
                ))

        # Run local validation
        validation_errors = _validate_circuit(updated_components)
        errors.extend(validation_errors)

        logger.info(f"Circuit designer finalized {len(updated_components)} components, {len(errors)} issues")

        circuit = CircuitStruct(
            metadata=blocks.metadata,
            blocks=blocks.blocks,
            components=updated_components,
        )
        return circuit, errors

    except (json.JSONDecodeError, ValueError) as e:
        logger.error(f"Circuit designer JSON parse error: {e}")
        # Fall back to the original components
        errors.append(CircuitError(
            component="*",
            error=f"Circuit designer returned invalid response: {e}. Using original component list.",
            severity="warning",
        ))
        circuit = CircuitStruct(
            metadata=blocks.metadata,
            blocks=blocks.blocks,
            components=components,
        )
        return circuit, errors


def _validate_circuit(components: List[BaseComponent]) -> List[CircuitError]:
    """
    Local validation rules for the finalized circuit.
    Returns a list of issues found.
    """
    errors: List[CircuitError] = []
    signal_users: Dict[str, List[str]] = defaultdict(list)

    for comp in components:
        has_gnd = False
        has_power = False
        prefix = "".join(c for c in comp.designator if c.isalpha()).upper()

        for pin in comp.pins:
            sig = pin.signal_name or ""
            signal_users[sig].append(comp.designator)

            if sig.upper() in ("GND", "DGND", "AGND", "PGND"):
                has_gnd = True
            if sig.upper() in ("VCC", "VCC_3V3", "VCC_5V", "VCC_12V", "VIN", "VBAT", "VDD"):
                has_power = True

        # ICs should have both GND and power
        if prefix in ("U",) and len(comp.pins) > 4:
            if not has_gnd:
                errors.append(CircuitError(
                    component=comp.designator,
                    error=f"{comp.designator} ({comp.value}): No GND connection found. Add GND pin.",
                    severity="warning",
                ))
            if not has_power:
                errors.append(CircuitError(
                    component=comp.designator,
                    error=f"{comp.designator} ({comp.value}): No power (VCC/VDD) connection found.",
                    severity="warning",
                ))

    # Check for signals that appear only once (dangling connections)
    power_nets = {"GND", "VCC", "VCC_3V3", "VCC_5V", "VCC_12V", "VIN", "VBAT", "VDD", "NC", "UNCONNECTED"}
    for signal, users in signal_users.items():
        if signal.upper() in power_nets:
            continue
        if not signal or signal.upper() == "NC":
            continue
        if len(users) < 2:
            errors.append(CircuitError(
                component=users[0] if users else "unknown",
                error=f"Signal '{signal}' appears only on {users[0] if users else '?'}. Likely a dangling connection.",
                severity="info",
            ))

    return errors
