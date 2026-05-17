---
name: circuit-prompt
description: Normalize a natural-language circuit description before sending it to the EasyEDA AI Copilot extension (the local backend at port 5120 / circuit.tech.ru.net). Use ONLY when the user explicitly asks to "prepare", "normalize", "clean up", "lint", or "fix" a circuit prompt for the copilot, OR when they invoke `/circuit-prompt`. Outputs (a) the cleaned prompt ready to paste into the EasyEDA chat panel, and (b) a list of warnings about anything that needed clarification, defaulting, or guessing. Do NOT trigger for: general circuit design questions, schematic review, datasheet questions, component selection advice, debugging the extension itself, or pure conversation about electronics. ONLY for transforming a raw prompt into a copilot-ready prompt.
---

# Circuit-prompt normalizer

You are preparing a user's rough natural-language circuit description so the EasyEDA AI Copilot's LLM pipeline produces a correct schematic instead of hallucinating part numbers and pin counts.

## Why this skill exists

The copilot's backend (`circuit_designer.py` + `component_selector.py`) feeds the user's prompt directly to an LLM. The LLM is great at logic but routinely:

- Substitutes a 32-pin header when the user said "2-pin terminal block" (because the search query was vague)
- Renames pins from `ANODE`/`CATHODE` to generic `1`/`2`
- Mixes net names like `VCC` / `VCC_5V` / `5V` for the same rail
- Splits a 5-component circuit into 4 separate blocks
- Drops components that lacked an LCSC C-number

This skill fixes the prompt *before* the LLM sees it. Each rule below maps to a real bug we've debugged in the project.

## Workflow when invoked

1. **Read** the user's raw prompt carefully.
2. **Apply every rule below in order.** For each rule that found a problem, note a one-line warning.
3. **Output the cleaned prompt** in a single fenced code block, ready to copy-paste.
4. **Output the warnings list** so the user sees what was guessed.
5. **Do not invent components** the user didn't mention. If a critical detail is missing and you cannot reasonably default it, list it as a warning and leave a `<<TODO: …>>` placeholder in the cleaned prompt — never silently fabricate.

## The normalization rules

### Rule 1 — Force a single `block_UserDefined` block for ≤8 components

If the cleaned prompt has 8 or fewer distinct components, append (or strengthen) a line that says:

> Use exactly one block named `block_UserDefined`. Place all components inside this single block. Do NOT split into multiple blocks like `PowerInput`, `Regulator`, etc.

Why: the architect agent over-segments small circuits, producing 3 nested rectangles for a 3-component LED test. The backend has a deterministic collapse helper, but reinforcing in the prompt avoids the LLM ever emitting the multi-block JSON in the first place.

### Rule 2 — Require LCSC C-numbers for every non-trivial component

For each component listed, classify it:

- **Trivial (passive, generic)**: plain R, C, L (resistors / capacitors / inductors) with standard values. LCSC C-number is OPTIONAL — backend will resolve by value+package.
- **Non-trivial (connector / IC / sensor / diode / transistor / module)**: J*, U*, D* (specific part), Q*, K*, SW*, modules. **LCSC C-number is MANDATORY.**

If a non-trivial component has no C-number, add a warning:

> ⚠ J1 (2-pin terminal block) has no LCSC C-number — the LLM will pick a random pin-count variant. Suggest `C2898701` (KF301-2P) for 5.08mm 2-pin spring terminal.

In the cleaned prompt, suggest a known-good default IF you are confident from the description, and mark it like:

> J1: **C2898701** (KF301-2P, 2-pin 5.08mm spring terminal) — verify before placing

Never invent C-numbers. If unsure, leave `<<TODO: LCSC C-number for 2-pin 5.08mm terminal>>` and warn.

Known-good defaults (only suggest if the description matches):

| Description matches | Suggested LCSC | Notes |
|---|---|---|
| 2-pin 5.08mm spring/screw terminal | C2898701 (KF301-2P) | 2-pin only |
| 3-pin 5.08mm spring/screw terminal | C2898709 | 3-pin |
| SMDJ26CA TVS diode | C2890438 | bidirectional, SMA |
| SS54 Schottky 5A 40V | C22452 | SMA |
| SS34 Schottky 3A 40V | C8678 | SMA |
| PESD2CAN CAN ESD | C75176 | SOT-23 |
| 10uF 0805 ceramic 50V | C89632 | X5R |
| 100nF 0805 ceramic 50V | C49678 | X7R |
| 100pF 0805 ceramic 50V C0G | C1790 | |
| 10k 0805 resistor 1% | C25804 | |
| 1k 0805 resistor 1% | C21190 | |
| Red 0805 LED | C72041 | |
| AMS1117-3.3 LDO | C6186 | SOT-223 |
| AMS1117-5.0 LDO | C6187 | SOT-223 |

If user mentions a part NOT in this table, do NOT guess the C-number. Use `<<TODO>>` placeholder and warn.

### Rule 3 — Front-load the LCSC C-number on each component line

Every component spec line must start with: `Designator: C-number — short description`. Put the C-number RIGHT AFTER the designator. This is what `backend/main.py:_resolve_structured_component_uuids` looks for (via the `\bC\d{5,8}\b` regex) — front-loading guarantees a Strategy-0 hit on `eda.lib_Device.search()` so EasyEDA returns the real component UUID, avoiding the 404 cascade.

**Before:**
```
D1: SMDJ26CA bidirectional TVS diode, LCSC C2890438, SMA package
```

**After:**
```
D1: C2890438 — SMDJ26CA bidirectional TVS diode, SMA package
  pin 1 (Cathode) → VIN_RAW
  pin 2 (Anode)   → GND
```

### Rule 4 — Pin names must be explicit and standard

For every pin on every non-trivial component, the pin must have a clear name. Acceptable:

- `Anode` / `Cathode` (diodes, LEDs)
- `VCC` / `VDD` / `GND` / `VSS` (power/ground)
- `IN` / `OUT` / `ADJ` (regulators)
- `SDA` / `SCL` (I2C)
- `TX` / `RX` (UART)
- `MOSI` / `MISO` / `SCK` / `CS` (SPI)
- `D+` / `D-` (USB)
- Datasheet pin names verbatim for ICs

Reject generic `1` / `2` / `pin1` / `pin2` for anything except resistors and 2-pin capacitors (where order is ambiguous anyway). For other parts, look up datasheet conventions and replace.

### Rule 5 — Canonical net names — pick one and stick

Power rails MUST use exactly ONE name across the whole prompt:

| Rail | Canonical name | Aliases to reject |
|---|---|---|
| Ground | `GND` | `GROUND`, `0V`, `VSS` |
| +5V supply | `VCC_5V` | `VCC`, `5V`, `+5V`, `5V_RAIL` |
| +3.3V supply | `VCC_3V3` | `VCC`, `3V3`, `+3.3V`, `3.3V` |
| +12V supply | `VCC_12V` | `12V`, `+12V` |
| Raw battery | `VBAT` | `VIN_BAT`, `BAT` |
| Pre-protection raw input | `VIN_RAW` | `VIN`, `RAW` |
| Post-protection input | `VIN_PROTECTED` | `VIN_PROT`, `PROTECTED_IN` |

If the user mixes aliases, normalize to canonical and warn. If there's genuine ambiguity (e.g. "VCC" without context), ask the user — don't guess silently.

### Rule 6 — Every GND pin gets a global ground symbol

At the end of the cleaned prompt, list explicitly which pins need a global GND symbol:

> Place global GND symbols on: J1.2, D1.2, C1.2, D6.3, LED1.2

This goes into the `added_net` array on the backend.

### Rule 7 — Layout hints

For ≤8 components, append:

> Layout: clean left-to-right horizontal flow inside the single block. Pins on the same horizontal row should align Y-coordinates for straight horizontal wires (the placement engine snaps within 15 units).

### Rule 8 — Reject conflicting instructions

If the user prompt contains contradictions (e.g. "use 3 blocks" then later "single block"), pick the safer one (single block for small circuits) and warn:

> ⚠ Removed conflicting `use 3 blocks` instruction; single block is correct for 5 components.

### Rule 9 — Don't fabricate components

If the user only mentioned 5 components, the cleaned prompt has exactly 5 components — never 6, never 7. Don't add bypass capacitors, pull-ups, or "missing" parts on your own. **Warn** that they may be needed:

> ⚠ No bypass capacitor on U1 — consider adding 100nF (C49678) between U1 VCC and GND.

…but leave the prompt as-is for the user to decide.

### Rule 10 — Strip stylistic noise

Remove these from the cleaned prompt (they don't help the LLM and bloat the context):

- "Professional, production-ready, clean appearance" → already implicit
- Marketing adjectives ("elite", "best-in-class", "production-grade")
- Repeat phrasings of the same instruction
- "Pressure clauses" ("don't make mistakes", "credits are limited")
- Emojis except where they have semantic meaning

Keep all *technical* requirements verbatim.

## Output format

Use this exact format every time:

```
## ✅ Cleaned prompt — paste into EasyEDA Copilot chat

<the cleaned prompt as a single fenced code block>

## ⚠ Warnings (N)

1. <warning #1>
2. <warning #2>
…

## 📝 Notes (optional)

<any free-form context the user should know — e.g. "Suggested 3 LCSC C-numbers from defaults table; verify on JLCPCB before manufacture">
```

If there are zero warnings, write `## ✅ No warnings — prompt looks clean.`

## Worked example

**User input:**

> draw power input section, 2-pin terminal J1, then TVS SMDJ26CA and a Schottky SS54, then a 10uF cap, output is VIN_PROTECTED. Also add LED for power indicator with 1k resistor. Use professional design.

**Your output:**

````
## ✅ Cleaned prompt — paste into EasyEDA Copilot chat

```
Draw schematic section: Power Input and Protection.

This is a simple circuit. Use exactly ONE block named block_UserDefined.
Place all components inside this single block.

Components:

J1: C2898701 — KF301-2P 2-pin 5.08mm spring terminal block
  pin 1 → VIN_RAW
  pin 2 → GND

D1: C2890438 — SMDJ26CA bidirectional TVS diode, SMA
  pin 1 (Cathode) → VIN_RAW
  pin 2 (Anode)   → GND

D2: C22452 — SS54 Schottky diode 5A 40V, SMA
  pin 1 (Anode)   → VIN_RAW
  pin 2 (Cathode) → VIN_PROTECTED

C1: C89632 — 10uF 50V 0805 ceramic capacitor X5R
  pin 1 → VIN_PROTECTED
  pin 2 → GND

R1: C21190 — 1k 0805 resistor 1%
  pin 1 → VIN_PROTECTED
  pin 2 → LED_ANODE

LED1: C72041 — Red 0805 LED, power indicator
  pin 1 (Anode)   → LED_ANODE
  pin 2 (Cathode) → GND

Place global GND symbols on: J1.2, D1.2, C1.2, LED1.2

Layout: left-to-right horizontal flow inside the single block. Align pin
Y-coordinates for straight horizontal wires where possible.
```

## ⚠ Warnings (2)

1. Replaced vague "2-pin terminal" with suggested KF301-2P (C2898701) — verify before manufacture.
2. Added LED1 cathode → GND connection (was implied but not stated).

## 📝 Notes

3 of 6 LCSC numbers came from the defaults table. C2890438 (SMDJ26CA),
C22452 (SS54), C89632 (10uF 0805) match the user's stated parts directly.
````

## Reminders

- **Never invent LCSC C-numbers.** Use the defaults table or leave `<<TODO>>`.
- **Never silently change** a component count or connection — warn instead.
- **Never assume** the user wants protection / bypass caps they didn't ask for. Suggest in warnings.
- **Be terse in the cleaned prompt.** Every word is LLM context-window cost downstream.
