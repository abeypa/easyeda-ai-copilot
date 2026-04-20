# EasyEDA AI Copilot v2.1

AI-powered circuit design assistant for EasyEDA Pro — with a **local backend server** for privacy, reliability, and full customization.

## What It Does

- **Natural Language → Schematics**: Describe a circuit in plain English, get a production-ready schematic placed in EasyEDA
- **LCSC Part Lookup**: Automatically finds real LCSC/JLCPCB parts, checks stock, replaces out-of-stock components
- **Client-Side UUID Resolution**: When the backend LCSC search API is unavailable, the extension resolves component UUIDs directly via EasyEDA's built-in `eda.lib_Device.search()` SDK — ensuring assembly works even when external APIs are down
- **Multi-Block Layout**: Generates circuits organized into labeled blocks with no overlap
- **Assembly Error Reporting**: Shows per-component errors (missing connections, stock replacements) in the chat window
- **PCB Assembly**: Places components within a user-defined PCB boundary with fixed-part constraints
- **Multiple LLM Support**: Connect directly to OpenAI, Anthropic, Google, Deepseek, or any model via OpenRouter

## Architecture

```
EasyEDA Pro Extension (TypeScript/Vue 3)
        ↕ HTTP/SSE on localhost:5120
Local Python Backend (FastAPI)
        ↕ API calls
LLM Provider (OpenAI / Anthropic / OpenRouter)
 + LCSC Component Database (jlcsearch API — with circuit breaker)
 + Client-side fallback: eda.lib_Device.search() via EasyEDA SDK
```

All data stays on your machine. Your API keys are sent directly from the backend to the LLM provider — never to a third-party intermediary.

## Quick Start

### 1. Start the Backend Server

**Prerequisites**: Python 3.10+

**Linux/macOS:**
```bash
chmod +x start-backend.sh
./start-backend.sh
```

**Windows:**
```cmd
start-backend.bat
```

This installs dependencies and starts the server at `http://localhost:5120`.

### 2. Install the Extension in EasyEDA Pro

1. Open EasyEDA Pro
2. Go to **Settings → Extensions → Extension Manager**
3. Click **Import Extension**
4. Select `extension/build/dist/easyeda-ai-copilot-2.1.0.eext`
5. **Enable "External Interactions"** for the extension (required for backend communication)
6. Reload EasyEDA Pro

### 3. Configure

1. Open a schematic in EasyEDA Pro
2. Click **Copilot → Interface** in the top menu
3. Go to the **Settings** tab (gear icon)
4. Set:
   - **API Provider**: OpenAI, Anthropic, OpenRouter, etc.
   - **API Key**: Your key for the selected provider
   - **Backend URL**: `http://localhost:5120` (default, usually no change needed)
5. Click **Test Connection** to verify

## Features

### Schematic Generation
1. Open a schematic in EasyEDA Pro
2. Open the Copilot panel
3. Type a description: *"Design a 5V to 3.3V buck converter with LM2596, input capacitor, output capacitor, Schottky diode, and inductor"*
4. Click **Draw Whole Circuit** (purple button) or press Enter
5. The AI will:
   - Design the block diagram
   - Select real LCSC components
   - Check stock availability
   - Layout the circuit with proper spacing
   - Place all components and wires in your schematic

### Per-Block Assembly
After generating a circuit, each block shows an individual **Assemble** button. Click it to place only that block's components.

### LCSC Component Search
Ask: *"Find a 100Ω 1W SMD resistor"* — the AI searches LCSC and shows matching parts with stock status.

### PCB Assembly
1. Switch to the **PCB** tab in Copilot
2. Set board dimensions (width × height in mm)
3. Optionally mark fixed component positions
4. Click **Place Parts** — the AI suggests optimal placement
5. Click **Apply to PCB** to execute in EasyEDA

### Assembly Errors
All errors are displayed in the chat with severity colors:
- 🔵 **Info**: Stock replacement notifications
- 🟡 **Warning**: Unconnected pins, low stock
- 🔴 **Error**: Component not found, critical issues

### Model Display
The navbar shows the currently connected AI model and connection status (green/red dot).

## Building from Source

### Extension
```bash
cd extension
npm install
npm run build
```

Output: `extension/build/dist/easyeda-ai-copilot-2.1.0.eext`

### Backend
```bash
cd backend
pip install -r requirements.txt
python -m uvicorn main:app --host 0.0.0.0 --port 5120 --reload
```

## Supported LLM Providers

| Provider | Config | Notes |
|----------|--------|-------|
| OpenAI | `provider: openai` | GPT-4o, GPT-4o-mini, o1, etc. |
| Anthropic | `provider: anthropic` | Claude Sonnet, Opus, Haiku |
| OpenRouter | `provider: openrouter` | Any model (Llama, Mistral, Gemini, etc.) |
| Custom | Set `base-url` | Any OpenAI-compatible API (Ollama, vLLM, etc.) |

Each agent in the pipeline can use a different model. Configure in Settings → Agent Models.

## Project Structure

```
easyeda-ai-copilot/
├── backend/                    # Python FastAPI local server
│   ├── main.py                # Server + endpoint orchestration
│   ├── agents/                # LLM agent pipeline
│   │   ├── architect.py       # NL → block diagram
│   │   ├── component_selector.py  # Block → LCSC components
│   │   ├── circuit_designer.py    # Components → pin connections
│   │   └── pcb_placer.py     # PCB auto-placement
│   ├── lcsc/                  # LCSC part search + stock check
│   ├── layout/                # ELK-style layout engine
│   ├── llm/                   # LLM provider abstraction
│   └── models/                # Pydantic data models
├── extension/                 # EasyEDA Pro extension
│   ├── src/                   # Main thread (EDA API wrappers)
│   │   └── eda/               # assemble, schematic, pcb-place
│   ├── web/                   # IFrame UI (Vue 3 + Pinia)
│   │   └── src/
│   │       ├── components/    # Chat, PCB, Settings, shared
│   │       ├── composables/   # useChat, usePcbAssembly, useHealthCheck
│   │       └── stores/        # App state, settings, chat history
│   ├── extension.json         # Extension manifest
│   └── build/dist/            # Built .eext package
├── start-backend.sh           # Linux/Mac startup
├── start-backend.bat          # Windows startup
└── README.md
```

## API Endpoints (Backend)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/v2/chat/s/stream/new` | POST | Create SSE stream |
| `/v2/chat/s/stream/{id}` | GET | SSE event stream |
| `/v2/chat/s/stream/{id}/stop` | POST | Stop stream |
| `/v2/chat` | POST | Non-streaming chat |
| `/api/models` | GET | List available models |
| `/api/lcsc/search` | POST | Search LCSC components |
| `/api/lcsc/stock` | POST | Check stock + find equivalents |
| `/api/pcb/place` | POST | PCB component placement |
| `/api/health` | GET | Health check + model info |

## Why Local Backend (vs circuit.tech.ru.net)

The original extension used `circuit.tech.ru.net` as a remote backend. This version uses a local server because:

1. **Privacy**: API keys and schematic data never leave your machine
2. **Reliability**: No dependency on third-party server uptime
3. **Accuracy**: Full control over LLM prompts and circuit generation logic
4. **Customization**: Modify agents, add new features, tune behavior
5. **Speed**: No external network hop for orchestration
6. **Open Source**: Inspect, audit, and contribute to the backend code

## Credits

Based on [biosshot/easyeda-copilot](https://github.com/biosshot/easyeda-copilot) — rewritten with a local backend, PCB assembly support, and enhanced UI.

## License

Apache-2.0
