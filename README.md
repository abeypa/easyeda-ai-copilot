# ⚡ EasyEDA AI Copilot

An AI-powered circuit design assistant for [EasyEDA](https://easyeda.com) delivered as both a **browser extension** and a native **EasyEDA plugin**. Powered by [OpenRouter](https://openrouter.ai) — choose from Claude, GPT-4o, Gemini, DeepSeek, Llama, and more.

---

## Features

| Feature | Description |
|---|---|
| 💬 **AI Chat** | Expert circuit design assistant with streaming responses |
| ⚡ **Circuit Generator** | Describe → get component list + netlist + LCSC parts |
| 🔍 **Schematic Analyzer** | DRC, best-practice, and safety review of your schematic |
| 📋 **BOM Generator** | JLCPCB-ready BOM with LCSC part numbers |
| 🔧 **Model Selector** | Switch between 20+ OpenRouter models in one click |
| 📐 **EasyEDA Integration** | Reads live schematic data as AI context |

---

## Installation

### Option A — EasyEDA Plugin (Recommended)

1. Open **EasyEDA** → top menu → **Advanced → Plugins**
2. Click **Load Plugin from local directory…**
3. Select the `plugin/` folder from this repo
4. The AI Copilot panel appears in the right sidebar

### Option B — Chrome Extension

1. Open Chrome → `chrome://extensions`
2. Enable **Developer mode** (top-right toggle)
3. Click **Load unpacked**
4. Select the **root** of this repo (the folder containing `manifest.json`)
5. The ⚡ AI button appears on the right edge of every EasyEDA page

---

## Setup

1. Get a free API key at **[openrouter.ai/keys](https://openrouter.ai/keys)**
2. Open the plugin or extension popup
3. Paste your API key in **Settings → OpenRouter API Key**
4. Select your preferred model (Claude Sonnet 4.5 recommended for EDA tasks)
5. Click **Save Settings**

> Your API key is stored locally in `localStorage` / `chrome.storage.sync` and is never sent anywhere except directly to `openrouter.ai`.

---

## Usage

### 💬 Chat Tab
Ask anything about electronics:
- *"What value bulk capacitors should I use for a 2A 5V buck converter?"*
- *"How do I calculate the feedback resistors for LM2596?"*
- *"My ESP32 is resetting randomly — what could cause this?"*

The chat automatically includes your current EasyEDA schematic as context.

### ⚡ Generate Tab
Describe your circuit and get a full design:
- Component list with LCSC part numbers
- Netlist showing how components connect
- Design notes and PCB layout guidance
- Export as KiCad netlist or CSV BOM

### 🔍 Analyze Tab
Click **Load from EasyEDA** → **Analyze Schematic** to get:
- Critical issues (floating nets, missing protection)
- Warnings (missing decoupling caps, suboptimal values)
- Best-practice suggestions
- Overall design score

### 📋 BOM Tab
Generate a JLCPCB-ready BOM:
- From your loaded schematic
- Or from a manual component description
- Includes Basic/Extended part classification
- Export as Markdown or CSV

---

## Project Structure

```
easyeda-ai-copilot/
├── manifest.json              # Chrome Extension Manifest V3
├── plugin/
│   ├── plugin.json            # EasyEDA plugin metadata
│   ├── index.html             # Plugin UI entry point
│   ├── css/style.css          # Dark theme UI styles
│   └── js/
│       ├── app.js             # Main application orchestrator
│       ├── openrouter.js      # OpenRouter streaming API client
│       ├── easyeda.js         # EasyEDA API wrapper
│       ├── prompts.js         # Engineered system prompts
│       ├── generator.js       # Circuit generation logic
│       ├── analyzer.js        # Schematic analysis logic
│       └── ui.js              # UI utilities & markdown renderer
└── extension/
    ├── background/
    │   └── service-worker.js  # API proxy & extension lifecycle
    ├── content/
    │   ├── content.js         # Floating sidebar injection
    │   └── content.css        # Sidebar styles
    ├── popup/
    │   ├── popup.html         # Extension popup
    │   ├── popup.js           # Popup logic + key validation
    │   └── popup.css          # Popup styles
    └── icons/                 # Extension icons
```

---

## Supported Models (via OpenRouter)

| Model | Best For | Speed |
|---|---|---|
| `anthropic/claude-sonnet-4-5` | EDA tasks, reasoning | Fast |
| `anthropic/claude-3.5-sonnet` | Complex analysis | Fast |
| `openai/gpt-4o` | General purpose | Fast |
| `google/gemini-pro-1.5` | Long schematics | Medium |
| `deepseek/deepseek-r1` | Step-by-step reasoning | Medium |
| `meta-llama/llama-3.1-8b-instruct` | Free tier | Very fast |

---

## Development

```bash
# Clone the repo
git clone https://github.com/abeypa/easyeda-ai-copilot
cd easyeda-ai-copilot

# No build step required — pure HTML/CSS/JS
# Load the plugin/ folder in EasyEDA
# Or load the repo root as an unpacked Chrome extension
```

To generate proper PNG icons (optional):
```bash
npm install sharp
node extension/icons/generate-icons.js
```

---

## Contributing

Pull requests welcome! Key areas:

- **More prompts** — specialized prompts for RF, power, motor control
- **EasyEDA API** — deeper integration (auto-place components, draw wires)
- **Firmware generator** — generate Arduino/ESP-IDF/MicroPython code from schematics
- **Component DB** — offline LCSC component database for faster lookups

---

## License

MIT © EasyEDA AI Copilot Contributors
