# EasyEDA AI Copilot v2.1 — Change Log

## Summary

This release makes the extension resilient to LCSC search API outages by adding client-side UUID resolution via EasyEDA's built-in SDK, adding a circuit breaker to the backend LCSC search, parallelizing LCSC lookups, and reducing health check polling frequency.

---

## 1. Backend: `backend/lcsc/search.py` — Circuit Breaker + Fault Tolerance

**Problem:** The backend relied on `jlcsearch.tscircuit.com` which may return 502 errors, causing the entire component selection pipeline to stall.

**Changes:**
- Added a module-level circuit breaker (`_circuit_breaker` dict) with 3-failure threshold and 5-minute reset window
- Added `_check_breaker()`, `_record_failure()`, `_record_success()` helper functions
- `search_components()` now checks the breaker before making HTTP calls — returns empty list if circuit is open
- Records success/failure on every HTTP response (200 = success, non-200 or exception = failure)
- Reduced HTTP client timeout from 20s to 5s (`httpx.AsyncClient(timeout=5.0)`)
- After 3 consecutive failures, all LCSC lookups are skipped for 5 minutes (logged as warning)

## 2. Backend: `backend/agents/component_selector.py` — Parallel LCSC Resolution

**Problem:** LCSC UUID resolution was sequential — each component waited for the previous one to finish, making it very slow for large circuits.

**Changes:**
- Added `import asyncio` at the top
- Rewrote `_resolve_lcsc_uuids()` to use `asyncio.gather()` with a semaphore (max 5 concurrent lookups)
- Each individual lookup has a 5-second timeout via `asyncio.wait_for()`
- Added a failure counter: after 3 failures, remaining components are skipped with a warning log
- All components are resolved in parallel, significantly reducing total resolution time

## 3. Backend: `backend/main.py` — Health Check (No Changes Needed)

The GET `/api/health` endpoint already accepts `provider` and `model` query parameters (lines 1069-1070). The POST endpoint also works correctly. No backend changes were needed here.

## 4. Extension: `extension/web/src/composables/useHealthCheck.ts` — Reduced Polling

**Problem:** Health check polled every 15 seconds, creating unnecessary traffic.

**Changes:**
- Changed default interval from `15000` (15s) to `30000` (30s)
- The composable already uses only POST (not GET + POST), so no dual-request issue exists

## 5. Extension: `extension/src/eda/resolve-uuids.ts` — Main Thread UUID Resolution (NEW)

**Problem:** Backend returns components with `part_uuid: null` when LCSC search fails. These components can't be placed in EasyEDA without a valid UUID.

**Changes:**
- Created new file `extension/src/eda/resolve-uuids.ts`
- Exports `resolveComponentUuids()` function that iterates over components with missing UUIDs
- Uses `eda.lib_Device.search(query)` (EasyEDA Pro SDK) to find LCSC components
- Matches by name, supplierId, manufacturerId, or falls back to first result
- Skips already-resolved UUIDs (32-char hex) and special markers (`GND`, `VCC`)
- Catches errors per-component — one failure doesn't block others

## 6. Extension: `extension/src/eda/assemble.ts` — Integrated UUID Resolution

**Changes:**
- Added `import { resolveComponentUuids } from './resolve-uuids'`
- At the start of `assembleCircuit()`, before placing components, calls `await resolveComponentUuids(circuit.components)`
- Wrapped in try/catch so UUID resolution errors don't prevent assembly

## 7. Extension: `extension/web/src/eda/resolve-uuids.ts` — Iframe-Side UUID Resolution (NEW)

**Changes:**
- Created iframe-side version that checks if `eda.lib_Device.search` is available
- If not available in iframe context, gracefully returns (main thread handles it)
- If available, performs the same resolution logic as the main thread version

## 8. Extension: `extension/web/src/components/chat/circuit/CircuitAgentResultViewer.vue` — Pre-Assembly Resolution

**Changes:**
- Added `import { resolveComponentUuids } from '../../../eda/resolve-uuids'`
- In `assembleBlock()`: calls `await resolveComponentUuids(partialCircuit.components)` before `assembleCircuit()`
- In `assembleCircuitHandler()`: calls `await resolveComponentUuids(props.result.circuit.components)` before `assembleCircuit()`

## 9. `README.md` — Updated Documentation

**Changes:**
- Updated title from v2.0 to v2.1
- Added "Client-Side UUID Resolution" feature description
- Updated architecture diagram to show circuit breaker and client-side fallback
- Updated build output filename to v2.1.0

---

## Architecture: UUID Resolution Flow

```
Backend (component_selector.py)
  ├─ LLM generates components with search_query, part_uuid: null
  ├─ _resolve_lcsc_uuids() tries jlcsearch (parallel, with circuit breaker)
  └─ Returns components (some may still have null UUIDs if LCSC is down)

Extension Main Thread (src/eda/assemble.ts)
  ├─ assembleCircuit() called from iframe
  ├─ resolveComponentUuids() fills in remaining null UUIDs via eda.lib_Device.search()
  └─ Proceeds with component placement using resolved UUIDs

Extension Iframe (web/src/components/.../CircuitAgentResultViewer.vue)
  ├─ assembleBlock() / assembleCircuitHandler()
  ├─ resolveComponentUuids() pre-check (may be no-op in iframe)
  └─ Calls assembleCircuit() → main thread handles final resolution
```

This dual-layer approach ensures assembly works even when:
1. `jlcsearch.tscircuit.com` is completely down (circuit breaker prevents stalling)
2. Backend LCSC search returns no results (client-side SDK search fills gaps)
3. Both fail (components without UUIDs are skipped with error toast messages)
