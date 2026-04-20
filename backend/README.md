# EasyEDA AI Copilot — Local Backend

A local Python FastAPI server that replaces the third-party `circuit.tech.ru.net` backend.
Runs on `http://localhost:5120`.

## Quick Start

### Linux/macOS
```bash
cd easyeda-ai-copilot
./start-backend.sh
```

### Windows
```
cd easyeda-ai-copilot
start-backend.bat
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/v2/chat/s/stream/new` | Create new SSE stream, returns `{ streamId }` |
| GET | `/v2/chat/s/stream/{streamId}` | SSE event stream (reconnectable via `?last-event-id=`) |
| POST | `/v2/chat/s/stream/{streamId}/stop` | Stop a stream |
| POST | `/v2/chat` | Non-streaming chat fallback |
| GET | `/api/models` | List available models |
| POST | `/api/lcsc/search` | LCSC component search |
| POST | `/api/lcsc/stock` | Stock check + equivalents |
| POST | `/api/pcb/place` | PCB component placement |
| GET | `/api/health` | Health check |

## Architecture

```
backend/
├── main.py                  # FastAPI server, SSE streaming, intent detection
├── requirements.txt
├── models/
│   ├── circuit.py           # Circuit data types (matches TypeScript types)
│   └── pcb.py               # PCB placement types
├── llm/
│   ├── provider.py          # Abstract LLM provider base class
│   ├── openai_provider.py   # OpenAI + compatible (Deepseek, etc.)
│   ├── anthropic_provider.py # Anthropic Claude
│   ├── openrouter_provider.py # OpenRouter (any model)
│   └── factory.py           # Provider selection based on llmSettings
├── agents/
│   ├── architect.py         # NL → Block diagram (CircuitBlocks)
│   ├── component_selector.py # Blocks → Components + LCSC search
│   ├── circuit_designer.py  # Pin connection validation
│   └── pcb_placer.py        # PCB component placement
├── lcsc/
│   ├── search.py            # jlcsearch.tscircuit.com API
│   └── stock.py             # Stock check + equivalent replacement
└── layout/
    └── elk_layout.py        # Pure Python hierarchical layout engine
```

## SSE Event Format

```
event: status
data: Designing block diagram...

event: mes_chunk
data: I'll design a circuit for you...

event: think_chunk
data: Internal reasoning text...

event: message
data: {"role":"ai","content":"{\"type\":\"circuit_agent_result\",...}","options":{},"isReady":true}

event: update-todos
data: [{"status":"completed","content":"Analyzing circuit requirements"},...]

event: end
data: 
```

## LLM Providers

Set in the extension Settings panel:
- **OpenAI** (`provider: "openai"`) — requires OpenAI API key
- **Anthropic** (`provider: "anthropic"`) — requires Anthropic API key  
- **OpenRouter** (`provider: "openrouter"`) — requires OpenRouter API key (access to all models)
- **Custom** — set `base-url` to point to any OpenAI-compatible endpoint (Ollama, LM Studio, Deepseek, etc.)

## Circuit Generation Pipeline

1. **Architect** — NL description → Block diagram (`CircuitBlocks`)
2. **Component Selector** — Blocks → Real LCSC components with UUIDs
3. **Circuit Designer** — Validates pin connections, ensures signal consistency
4. **Stock Check** — Verifies LCSC stock, finds equivalents for out-of-stock parts
5. **ELK Layout** — Positions components, routes wires → `CircuitAssembly`

The final `CircuitAssembly` is what the EasyEDA extension's `assembleCircuit()` consumes
to place components and draw wires on the schematic.

## LCSC Integration

Uses `jlcsearch.tscircuit.com` (free, no auth):
- `GET /components/list.json?search={query}&full=true`
- `GET /resistors/list.json?search={query}&full=true`
- `GET /capacitors/list.json?search={query}&full=true`
- etc.

LCSC part numbers are converted to 32-char hex UUIDs for EasyEDA using MD5.
