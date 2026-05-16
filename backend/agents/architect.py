"""
Circuit Architect Agent

Takes a natural language description and produces a structured block diagram:
  CircuitBlocks = { metadata, blocks[] }

Each block represents a functional sub-circuit (e.g., "Power Supply", "Amplifier").
Blocks reference each other via next_block_names to show signal flow.

The LLM is prompted to produce valid JSON matching the CircuitBlocks schema.
"""

from __future__ import annotations
import json
import logging
from typing import List, Optional

from llm.provider import LLMProvider, LLMMessage
from models.circuit import CircuitBlocks, Block, CircuitMetadata

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an expert electronics engineer specializing in circuit architecture and system design.

Your task is to analyze a natural language circuit description and produce a structured BLOCK DIAGRAM in JSON format.

## Output Format

Return ONLY valid JSON matching this exact schema:
```json
{
  "metadata": {
    "project_name": "Short project name",
    "description": "One-sentence description of the complete circuit"
  },
  "blocks": [
    {
      "name": "BlockName",
      "description": "What this sub-circuit does",
      "next_block_names": ["OtherBlock", "AnotherBlock"]
    }
  ]
}
```

## Rules

1. **Block names**: Short, unique, PascalCase or snake_case. No spaces. No "block_" prefix. Max 20 chars.
   CORRECT: "PowerSupply", "SignalAmplifier", "MCU", "USB_Interface", "Display"
   WRONG: "block_PowerSupply", "Power Supply", "power supply"

2. **Signal flow**: `next_block_names` shows where the OUTPUT of this block goes.
   - Power supply block → sends power to all other blocks
   - Sensor block → sends data to MCU block
   - MCU block → sends display data to Display block

3. **Completeness**: Include ALL necessary blocks:
   - Always include a power supply/regulation block if circuit uses ICs
   - Include bypass capacitors as part of the IC block (not separate)
   - Include protection components (TVS, fuses) in the relevant block
   - Include any required pull-up/pull-down resistors in the connected IC block

4. **Granularity** — CRITICAL BLOCK STRATEGY:
   - If the user describes a SIMPLE / TEST / BASIC circuit, OR the circuit will have **8 or fewer components total**, output EXACTLY ONE block named `UserDefined` containing every component. Do NOT split a 3-component LED test into PowerInput / CurrentLimit / LED — collapse it into one block.
   - Keywords that ALWAYS force a single `UserDefined` block: "simple", "test", "basic", "demo", "minimal", "smoke test", "sanity check", "blink test", "LED test".
   - For larger circuits, aim for 3-8 blocks. Don't over-segment.
   - Simple LED blinker (<=8 parts): 1 block (UserDefined)
   - Audio amplifier: 4-5 blocks (Power, Input Filter, Preamp, Output Stage, Speaker Protection)
   - IoT device: 5-7 blocks (Power, MCU, Sensor, Communication, Display, Battery Monitor)

5. **Practicality**: Design for real-world PCB assembly using LCSC-available components.

## Examples

For "Arduino-based temperature logger with LCD display":
- UserDefined (single block, <=8 components)

For "Class D audio amplifier with Bluetooth input":
- PowerSupply: 12-24V DC input with filtering
- BluetoothModule: Bluetooth audio receiver (CSR8645 or similar)
- InputFilter: Low-pass filter and line level adjustment
- ClassD_Amp: TPA3116 or PAM8403 Class D amplifier IC
- SpeakerProtection: DC offset protection and speaker relay
- OutputFilter: LC output filter for speaker

Return ONLY the JSON. No explanation, no markdown, no code fences. Pure JSON only.
"""


async def run_architect(
    description: str,
    provider: LLMProvider,
    model: Optional[str] = None,
    conversation_context: Optional[List[dict]] = None,
) -> CircuitBlocks:
    """
    Run the Circuit Architect agent.
    
    Args:
        description: Natural language circuit description from the user
        provider: LLM provider instance
        model: Optional model override
        conversation_context: Optional previous conversation for context
    
    Returns:
        CircuitBlocks with metadata and block list
    
    Raises:
        ValueError: If the LLM returns invalid JSON or schema mismatch
    """
    messages = [
        LLMMessage(role="system", content=SYSTEM_PROMPT),
    ]

    # Add relevant conversation context (previous circuit results, if any)
    if conversation_context:
        context_text = _format_context(conversation_context)
        if context_text:
            messages.append(LLMMessage(
                role="user",
                content=f"Previous conversation context:\n{context_text}\n\n---\n\nNow design:"
            ))

    messages.append(LLMMessage(
        role="user",
        content=f"Design a block diagram for the following circuit:\n\n{description}",
    ))

    logger.info(f"Running architect agent for: {description[:100]}...")

    response = await provider.complete(
        messages=messages,
        model=model,
        temperature=0.2,
        max_tokens=4096,
    )

    # Parse and validate the JSON response
    try:
        data = response.extract_json()
        
        # Sanitize block names: strip any "block_" prefix that the LLM might have added
        blocks_raw = data.get("blocks", [])
        for b in blocks_raw:
            name = b.get("name", "")
            if name.startswith("block_"):
                b["name"] = name[6:]  # strip "block_" prefix
        
        result = CircuitBlocks(
            metadata=CircuitMetadata(**data["metadata"]),
            blocks=[Block(**b) for b in blocks_raw],
        )
        logger.info(f"Architect produced {len(result.blocks)} blocks: {[b.name for b in result.blocks]}")
        return result

    except (KeyError, TypeError, json.JSONDecodeError, ValueError) as e:
        logger.error(f"Architect JSON parse error: {e}\nResponse: {response.content[:500]}")
        raise ValueError(f"Architect agent returned invalid JSON: {e}") from e


def _format_context(context: List[dict]) -> str:
    """Format conversation context for inclusion in the prompt."""
    lines = []
    for msg in context[-6:]:  # Last 6 messages for context
        role = msg.get("role", "unknown")
        content = str(msg.get("content", ""))
        if len(content) > 500:
            content = content[:500] + "..."
        lines.append(f"[{role}]: {content}")
    return "\n".join(lines)
