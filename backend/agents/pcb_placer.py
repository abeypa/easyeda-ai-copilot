"""
PCB Placer Agent

Takes a component list + board boundary + fixed parts, and uses the LLM
to suggest optimal component placement positions on the PCB.

Returns PlacedComponent list with x,y positions in millimeters.
"""

from __future__ import annotations
import json
import logging
from typing import List, Optional

from llm.provider import LLMProvider, LLMMessage
from models.pcb import (
    PCBPlacementRequest,
    PCBPlacementResult,
    PlacedComponent,
)

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an expert PCB layout engineer with 15+ years of experience designing production PCBs.

Your task is to suggest optimal component placement positions for PCB layout.

## Input
You will receive:
- Board boundary dimensions (in mm)
- Component list from the schematic BOM
- Fixed parts (components with pre-assigned positions)
- Design constraints (minimum spacing, keep-out zones)

## Output Format

Return ONLY valid JSON:
```json
{
  "placed_components": [
    {
      "designator": "U1",
      "x": 50.0,
      "y": 40.0,
      "side": "top",
      "rotation": 0.0,
      "rationale": "Centered on board, MCU as central hub"
    }
  ],
  "notes": "Overall placement strategy description",
  "warnings": ["Warning about tight spacing near J1", "Consider heatsink for U2"]
}
```

## Placement Rules

### Coordinate System
- Origin (0,0) at BOTTOM-LEFT corner of the board
- X increases to the RIGHT
- Y increases UPWARD
- All positions in MILLIMETERS
- Position = center of component

### Component Placement Best Practices

1. **Power components first** (voltage regulators, power connectors):
   - Place power input connector (J_PWR) near board edge
   - Place LDO/regulator near power input, away from heat-sensitive components
   - Add thermal relief around power components (>5mm from MCU)

2. **MCU placement** (U with many pins):
   - Center or slightly off-center for easy routing to all peripherals
   - Keep away from power mosfets and inductors
   - Leave 5mm+ clearance for programming header

3. **Connectors (J)**:
   - Always place at board EDGES (x < 5mm from edge or x > width-5mm)
   - USB: prefer bottom or left edge
   - Power: prefer top-right corner
   - Debug/JTAG: any edge, preferred bottom-right

4. **Bypass capacitors (C)**:
   - Place WITHIN 2mm of the IC they decouple
   - If multiple ICs on board, distribute bypass caps near each IC
   - Group by power rail

5. **Crystal/Oscillator (X)**:
   - Place ADJACENT to MCU (within 5mm)
   - Keep away from noisy signals (PWM, switching converters)

6. **Analog components (op-amps, ADC inputs)**:
   - Keep away from digital switching circuits
   - Place on opposite side of board from switching power supply

7. **LEDs and indicators**:
   - Near board edges for visibility
   - Group status LEDs together

### Minimum Spacing Guidelines
- Between SMD components: 0.5mm minimum
- SMD to board edge: 2mm minimum
- Through-hole to board edge: 3mm minimum
- Power components with heatsink: 5mm from neighbors

### Component Sizes (typical, for placement)
- 0402 passives (R, C): 1.0mm × 0.5mm
- 0603 passives: 1.6mm × 0.8mm
- 0805 passives: 2.0mm × 1.2mm
- SOT-23 (Q, small IC): 3.0mm × 1.7mm
- SOIC-8 (small IC): 5.0mm × 4.0mm
- SOIC-16: 10.0mm × 4.0mm
- QFN-32: 5.0mm × 5.0mm
- TSSOP-20: 6.5mm × 4.4mm
- 2-pin connector: 8.0mm × 5.0mm per pin pitch
- USB-C connector: 9.0mm × 7.0mm

Return ONLY the JSON. No explanation, no markdown.
"""


async def run_pcb_placer(
    request: PCBPlacementRequest,
    provider: LLMProvider,
    model: Optional[str] = None,
) -> PCBPlacementResult:
    """
    Run the PCB Placer agent.
    
    Args:
        request: PCB placement request with components, boundary, fixed parts, constraints
        provider: LLM provider instance
        model: Optional model override
    
    Returns:
        PCBPlacementResult with placed_components list
    """
    boundary = request.boundary
    fixed_parts = request.fixed_parts or []
    constraints = request.constraints

    # Format fixed parts for the prompt
    fixed_designators = {fp.designator for fp in fixed_parts}

    fixed_desc = ""
    if fixed_parts:
        fixed_list = [
            f"  - {fp.designator}: x={fp.x}mm, y={fp.y}mm, side={fp.side}, rotation={fp.rotation}°"
            for fp in fixed_parts
        ]
        fixed_desc = "FIXED (do not move):\n" + "\n".join(fixed_list)

    # Components to place (excluding fixed ones)
    components_to_place = [
        c for c in request.components
        if c.get("designator") not in fixed_designators
    ] if isinstance(request.components, list) else []

    # Format components list
    comp_lines = []
    for comp in components_to_place:
        des = comp.get("designator", "?")
        val = comp.get("value", "?")
        pins = len(comp.get("pins", []))
        sq = comp.get("search_query", "")
        comp_lines.append(f"  - {des}: {val} ({pins} pins) — {sq}")

    comps_desc = "\n".join(comp_lines) if comp_lines else "No components"

    # Build constraint description
    constraint_desc = ""
    if constraints:
        constraint_desc = f"\nConstraints:\n  - Min spacing: {constraints.min_spacing}mm"
        if constraints.keep_out_zones:
            for kz in constraints.keep_out_zones:
                constraint_desc += f"\n  - Keep-out: ({kz.x},{kz.y}) {kz.width}×{kz.height}mm"

    prompt = (
        f"PCB Board: {boundary.width}mm × {boundary.height}mm ({boundary.type})\n\n"
        f"{fixed_desc}\n\n"
        f"Components to place:\n{comps_desc}\n"
        f"{constraint_desc}\n\n"
        f"Place all non-fixed components using PCB layout best practices."
    )

    messages = [
        LLMMessage(role="system", content=SYSTEM_PROMPT),
        LLMMessage(role="user", content=prompt),
    ]

    logger.info(f"Running PCB placer for {len(components_to_place)} components on {boundary.width}×{boundary.height}mm board")

    response = await provider.complete(
        messages=messages,
        model=model,
        temperature=0.2,
        max_tokens=4096,
    )

    try:
        data = response.extract_json()
        placed = []

        # Include fixed parts in result
        for fp in fixed_parts:
            placed.append(PlacedComponent(
                designator=fp.designator,
                x=fp.x,
                y=fp.y,
                side=fp.side,
                rotation=fp.rotation,
                rationale="Fixed position (user-specified)",
            ))

        # Add LLM-suggested placements
        for p in data.get("placed_components", []):
            try:
                placed.append(PlacedComponent(
                    designator=p["designator"],
                    x=float(p["x"]),
                    y=float(p["y"]),
                    side=p.get("side", "top"),
                    rotation=float(p.get("rotation", 0)),
                    rationale=p.get("rationale"),
                ))
            except (KeyError, TypeError, ValueError) as e:
                logger.warning(f"Invalid placement entry: {e}")

        return PCBPlacementResult(
            placed_components=placed,
            notes=data.get("notes"),
            warnings=data.get("warnings"),
        )

    except (json.JSONDecodeError, ValueError, KeyError) as e:
        logger.error(f"PCB placer JSON parse error: {e}")
        raise ValueError(f"PCB placer returned invalid JSON: {e}") from e
