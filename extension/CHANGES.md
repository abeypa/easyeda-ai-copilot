# EasyEDA AI Copilot — Extension Changes

This document describes all changes made to the original easyeda-copilot repo to create the enhanced AI Copilot extension.

## 1. Backend URL — `web/src/api/index.ts`
- **Removed** hardcoded `circuit.tech.ru.net` URL and Basic auth header
- **Added** `getApiUrl()` function that reads from settings store (key: `backendUrl`), defaulting to `http://localhost:5120`
- Both DEV and production modes point to `localhost:5120`
- All `Authorization` headers removed — the local backend doesn't need them

## 2. Model Display — `web/src/components/layout/Navbar.vue`
- Added **status dot** (green = connected, red = offline)
- Added **model name display** next to the dot (e.g., "GPT-4o", "Claude Sonnet 3.5")
- Model info fetched from `GET /api/health` on the local backend
- Poll interval: every 20 seconds
- Powered by new `useHealthCheck.ts` composable

## 3. PCB Tab — `web/src/components/layout/Navbar.vue`
- Added **PCB tab** alongside Chat, Completions, Simulate, Settings

## 4. Draw Whole Circuit Button — `web/src/components/chat/ChatView.vue`
- Added **"CircuitBoard" icon button** in the chat input area
- When clicked, calls `sendMessage({ action: 'draw_circuit' })` — adds the action flag to the request body
- The backend uses this flag to route to the full circuit generation pipeline
- Button is disabled when input is empty or loading is in progress
- `useChat.ts` updated to accept either `boolean` (retry) or `Record<string, unknown>` (extra body fields)

## 5. Per-Block Assembly — `web/src/components/chat/circuit/CircuitAgentResultViewer.vue`
- Each block card now has an **"Assemble" button**
- Clicking assembles only the components belonging to that block
- Shows loading state ("Placing...") while assembling
- Filters components, edges, and nets to only the selected block before calling `assembleCircuit`

## 6. Assembly Error Display — `web/src/components/chat/AssemblyErrors.vue` (NEW)
- New component that displays assembly notices/errors per component
- **Blue** (info): stock replacements, informational
- **Yellow** (warning): unconnected pins, non-critical issues
- **Red** (error): component not found, critical failures
- Shows component designator + error message
- `CircuitAgentResultViewer` automatically renders this when `result.assembly_errors` is present

## 7. LCSC Stock Display — `CircuitAgentResultViewer.vue`
- Added inline **StockBadge** sub-component
- **Green** badge: "In Stock (1500)" when `stock_count >= 100`
- **Yellow** badge: "Low Stock (50)" when `stock_count < 100`
- **Red** badge: "Out of Stock — replaced with [alt]" when `stock_count === 0` or `stock_status === 'out_of_stock'`
- Also shows "Replaced:" detail row for components that were auto-swapped

## 8. PCB Assembly Tab — `web/src/components/pcb/PcbAssemblyView.vue` (NEW)
- **Board Boundary Input**: Rectangle (width × height mm) or polygon (list of X,Y points)
- Visual SVG preview of the board boundary
- **Fixed Parts Panel**: checkboxes to mark components as fixed with X/Y/rotation/side inputs
- **Load from Schematic** button reads BOM from EasyEDA Pro
- Manual "Add Component" to add parts not in schematic
- **Place Parts (AI)** button sends request to backend `/v2/chat` with `action: "pcb_place"`
- **Placement result** shown as SVG board preview with component dots (blue=top, orange=bottom)
- **Apply to PCB** button calls `eda.placePcbComponents()` to execute placement in EasyEDA

## 9. PCB Assembly Composable — `web/src/composables/usePcbAssembly.ts` (NEW)
- Manages all PCB assembly state
- `loadFromSchematic()` — reads BOM from EasyEDA Pro
- `requestPlacement()` — sends to backend AI for placement calculation
- `applyToEda()` — executes placement in EasyEDA Pro PCB editor

## 10. PCB Placement Extension API — `src/eda/pcb-place.ts` (NEW)
- Runs in extension main thread with access to EasyEDA Pro APIs
- `placePcbComponents(placements)` — moves/places components using `pcb_PrimitiveComponent.modify()`
- `isPcbEditorActive()` — detects if PCB editor is currently open
- Registered as `eda.placePcbComponents` and `eda.isPcbEditorActive`

## 11. Extension Manifest — `extension.json`
- Updated name to `easyeda-ai-copilot`, version `2.0.0`
- Added PCB menu with "Open Copilot (PCB)" and "About..." items
- Added "Interface" menu item to PCB section

## 12. Settings Enhancements — `web/src/components/settings/SettingsView.vue`
- Added **Backend Server** section at the top of settings
- **Backend URL** field (default: `http://localhost:5120`)
- **Test Connection** button — pings `/api/health` and shows result (green/red)
- Added **Google Gemini** to provider options
- `OpenRouter` now labeled "OpenRouter (any model)"

## 13. Settings Store — `web/src/stores/settings-store.ts`
- Added `backendUrl` setting with default `http://localhost:5120`
- `setSetting()` now allows any key (not just defaults) for extensibility

## 14. Health Check Composable — `web/src/composables/useHealthCheck.ts` (NEW)
- Polls `GET /api/health` on the configured backend URL
- Returns `{ connected, model, provider, version, error }`
- Friendly model name mapping (e.g., `claude-3-5-sonnet` → "Claude Sonnet 3.5")
- Poll interval configurable (default: 15s, Navbar uses 20s)

## Build
The extension builds to:
- `iframe/` — Vite-built Vue 3 web UI (loaded in IFrame)
- `dist/index.js` — ESBuild-compiled main thread code (TypeScript extension logic)
- Combined into `.eext` package for import into EasyEDA Pro

Build command: `npm run build`
