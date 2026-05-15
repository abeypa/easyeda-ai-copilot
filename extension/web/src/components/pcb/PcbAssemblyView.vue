<template>
  <div class="pcb-view">
    <!-- Error / status banner -->
    <div v-if="error" class="banner error-banner">{{ error }}</div>
    <div v-else-if="status" class="banner status-banner">{{ status }}</div>

    <!-- Board Boundary Section -->
    <section class="section">
      <h3 class="section-title">Board Boundary</h3>

      <div class="field-row">
        <label>Type</label>
        <select v-model="boundaryType" class="input-select">
          <option value="rectangle">Rectangle</option>
          <option value="polygon">Polygon</option>
        </select>
      </div>

      <template v-if="boundaryType === 'rectangle'">
        <div class="field-row">
          <label>Width (mm)</label>
          <input v-model.number="boundaryWidth" type="number" min="1" class="input-field" />
        </div>
        <div class="field-row">
          <label>Height (mm)</label>
          <input v-model.number="boundaryHeight" type="number" min="1" class="input-field" />
        </div>

        <!-- Visual preview of the rectangle -->
        <div class="board-preview-container">
          <svg
            class="board-preview"
            :viewBox="`0 0 ${previewW} ${previewH}`"
            :width="previewW"
            :height="previewH"
          >
            <rect x="2" y="2" :width="previewW - 4" :height="previewH - 4"
              fill="#1a3a1a" stroke="#4ade80" stroke-width="2" rx="2" />
            <text x="50%" y="50%" dominant-baseline="middle" text-anchor="middle"
              fill="#4ade80" font-size="10" font-family="monospace">
              {{ boundaryWidth }} × {{ boundaryHeight }} mm
            </text>
          </svg>
        </div>
      </template>

      <template v-if="boundaryType === 'polygon'">
        <p class="hint">Enter polygon points (one per line, format: X,Y in mm)</p>
        <textarea
          class="polygon-input"
          :value="polygonText"
          @input="onPolygonInput"
          rows="5"
          placeholder="0,0&#10;100,0&#10;100,80&#10;0,80"
        />
      </template>
    </section>

    <!-- Components Section -->
    <section class="section">
      <div class="section-header">
        <h3 class="section-title">Components</h3>
        <div class="section-actions">
          <button class="btn btn-secondary" @click="loadFromSchematic" :disabled="isLoading">
            <span v-if="isLoading">Loading...</span>
            <span v-else>Load from Schematic</span>
          </button>
          <button class="btn btn-secondary" @click="showAddComp = !showAddComp">+ Add</button>
        </div>
      </div>

      <!-- Manual add component -->
      <div v-if="showAddComp" class="add-comp-row">
        <input v-model="newCompDesignator" class="input-field" placeholder="Designator (e.g. U1)" />
        <input v-model="newCompValue" class="input-field" placeholder="Value (e.g. 100nF)" />
        <button class="btn btn-primary" @click="onAddComponent">Add</button>
      </div>

      <!-- Components table -->
      <div v-if="schematicComponents.length" class="components-table-container">
        <table class="components-table">
          <thead>
            <tr>
              <th>Fixed</th>
              <th>Designator</th>
              <th>Value</th>
              <th>X (mm)</th>
              <th>Y (mm)</th>
              <th>Rot°</th>
              <th>Side</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="comp in schematicComponents" :key="comp.designator"
              :class="{ 'row-fixed': isFixed(comp.designator) }">
              <td>
                <input type="checkbox"
                  :checked="isFixed(comp.designator)"
                  @change="toggleFixed(comp.designator, ($event.target as HTMLInputElement).checked)" />
              </td>
              <td class="mono">{{ comp.designator }}</td>
              <td class="val-cell">{{ comp.value }}</td>
              <template v-if="isFixed(comp.designator)">
                <td><input type="number" class="pos-input" :value="getFixedPart(comp.designator)?.x ?? 0"
                    @input="updateX(comp.designator, $event)" step="0.5" /></td>
                <td><input type="number" class="pos-input" :value="getFixedPart(comp.designator)?.y ?? 0"
                    @input="updateY(comp.designator, $event)" step="0.5" /></td>
                <td><input type="number" class="pos-input" :value="getFixedPart(comp.designator)?.rotation ?? 0"
                    @input="updateRot(comp.designator, $event)" step="45" /></td>
                <td>
                  <select class="side-select"
                    :value="getFixedPart(comp.designator)?.side ?? 'top'"
                    @change="updateSide(comp.designator, $event)">
                    <option value="top">Top</option>
                    <option value="bottom">Bot</option>
                  </select>
                </td>
              </template>
              <template v-else>
                <td colspan="4" class="auto-place-hint">Auto</td>
              </template>
            </tr>
          </tbody>
        </table>
      </div>

      <p v-else class="empty-hint">No components loaded. Click "Load from Schematic" or add manually.</p>
    </section>

    <!-- Placement Result -->
    <section v-if="placementResult" class="section">
      <div class="section-header">
        <h3 class="section-title">Placement Result</h3>
        <button class="btn btn-primary" @click="applyToEda" :disabled="isLoading">
          Apply to PCB
        </button>
      </div>

      <!-- Errors from placement -->
      <div v-if="placementResult.errors?.length" class="placement-errors">
        <div v-for="err in placementResult.errors" :key="err.designator" class="placement-error">
          <span class="err-des">{{ err.designator }}</span>: {{ err.message }}
        </div>
      </div>

      <!-- Placement board visualization -->
      <div class="result-preview-container">
        <svg class="result-preview"
          :viewBox="`0 0 ${resultPreviewW} ${resultPreviewH}`"
          :width="resultPreviewW" :height="resultPreviewH">
          <!-- Board background -->
          <rect x="2" y="2" :width="resultPreviewW - 4" :height="resultPreviewH - 4"
            fill="#1a3a1a" stroke="#4ade80" stroke-width="1.5" rx="2" />

          <!-- Component dots -->
          <g v-for="p in placementResult.placements" :key="p.designator">
            <circle
              :cx="mmToSvg(p.x, resultPreviewW)"
              :cy="mmToSvg(p.y, resultPreviewH)"
              r="6"
              :fill="p.side === 'bottom' ? '#f97316' : '#60a5fa'"
              opacity="0.85"
            />
            <text
              :x="mmToSvg(p.x, resultPreviewW)"
              :y="mmToSvg(p.y, resultPreviewH) + 16"
              text-anchor="middle"
              font-size="7"
              fill="#e2e8f0"
              font-family="monospace"
            >{{ p.designator }}</text>
          </g>
        </svg>
        <div class="legend">
          <span class="legend-dot" style="background:#60a5fa"></span> Top layer
          <span class="legend-dot" style="background:#f97316"></span> Bottom layer
        </div>
      </div>

      <!-- Placement table -->
      <div class="placement-table-container">
        <table class="components-table">
          <thead>
            <tr>
              <th>Designator</th>
              <th>X (mm)</th>
              <th>Y (mm)</th>
              <th>Rotation°</th>
              <th>Side</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="p in placementResult.placements" :key="p.designator">
              <td class="mono">{{ p.designator }}</td>
              <td>{{ p.x.toFixed(2) }}</td>
              <td>{{ p.y.toFixed(2) }}</td>
              <td>{{ p.rotation }}</td>
              <td>{{ p.side }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <!-- Action buttons -->
    <div class="action-bar">
      <button class="btn btn-primary btn-large" @click="requestPlacement" :disabled="isLoading || !schematicComponents.length">
        <span v-if="isLoading">⏳ Working...</span>
        <span v-else>Place Parts (AI)</span>
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue';
import { usePcbAssembly } from '../../composables/usePcbAssembly';

const {
  boundaryType,
  boundaryWidth,
  boundaryHeight,
  polygonPoints,
  fixedParts,
  schematicComponents,
  placementResult,
  isLoading,
  error,
  status,
  loadFromSchematic,
  addComponent,
  toggleFixed,
  updateFixedPosition,
  requestPlacement,
  applyToEda,
} = usePcbAssembly();

const showAddComp = ref(false);
const newCompDesignator = ref('');
const newCompValue = ref('');

// SVG preview dimensions
const PREVIEW_MAX = 160;
const aspectRatio = computed(() => boundaryWidth.value / boundaryHeight.value);
const previewW = computed(() => aspectRatio.value >= 1 ? PREVIEW_MAX : Math.round(PREVIEW_MAX * aspectRatio.value));
const previewH = computed(() => aspectRatio.value < 1 ? PREVIEW_MAX : Math.round(PREVIEW_MAX / aspectRatio.value));

// Result preview
const resultPreviewW = computed(() => {
  const bd = placementResult.value ? boundaryWidth.value : 100;
  const bh = placementResult.value ? boundaryHeight.value : 80;
  return bd >= bh ? 220 : Math.round(220 * (bd / bh));
});
const resultPreviewH = computed(() => {
  const bd = placementResult.value ? boundaryWidth.value : 100;
  const bh = placementResult.value ? boundaryHeight.value : 80;
  return bh >= bd ? 220 : Math.round(220 * (bh / bd));
});

function mmToSvg(mm: number, svgDim: number, boardDim?: number): number {
  const dim = boardDim ?? (svgDim === resultPreviewW.value ? boundaryWidth.value : boundaryHeight.value);
  return 4 + (mm / dim) * (svgDim - 8);
}

// Polygon text helper
const polygonText = computed(() =>
  polygonPoints.value.map(p => `${p.x},${p.y}`).join('\n')
);

function onPolygonInput(event: Event) {
  const text = (event.target as HTMLTextAreaElement).value;
  const points = text.split('\n').map(line => {
    const [x, y] = line.split(',').map(v => parseFloat(v.trim()));
    return { x: isNaN(x) ? 0 : x, y: isNaN(y) ? 0 : y };
  }).filter(p => !isNaN(p.x) && !isNaN(p.y));
  polygonPoints.value = points;
}

function onAddComponent() {
  if (!newCompDesignator.value.trim()) return;
  addComponent(newCompDesignator.value.trim(), newCompValue.value.trim());
  newCompDesignator.value = '';
  newCompValue.value = '';
  showAddComp.value = false;
}

function isFixed(designator: string): boolean {
  return fixedParts.value.find(p => p.designator === designator)?.fixed ?? false;
}

function getFixedPart(designator: string) {
  return fixedParts.value.find(p => p.designator === designator);
}

function updateX(designator: string, event: Event) {
  const part = getFixedPart(designator);
  if (!part) return;
  part.x = parseFloat((event.target as HTMLInputElement).value) || 0;
}

function updateY(designator: string, event: Event) {
  const part = getFixedPart(designator);
  if (!part) return;
  part.y = parseFloat((event.target as HTMLInputElement).value) || 0;
}

function updateRot(designator: string, event: Event) {
  const part = getFixedPart(designator);
  if (!part) return;
  part.rotation = parseFloat((event.target as HTMLInputElement).value) || 0;
}

function updateSide(designator: string, event: Event) {
  const part = getFixedPart(designator);
  if (!part) return;
  part.side = (event.target as HTMLSelectElement).value as 'top' | 'bottom';
}
</script>

<style scoped>
.pcb-view {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow-y: auto;
  padding: 0.75rem;
  gap: 0.75rem;
  box-sizing: border-box;
  font-size: 0.8rem;
}

.banner {
  padding: 0.5rem 0.75rem;
  border-radius: 5px;
  font-size: 0.78rem;
}

.error-banner {
  background: rgba(239, 68, 68, 0.1);
  border: 1px solid rgba(239, 68, 68, 0.4);
  color: #ef4444;
}

.status-banner {
  background: rgba(59, 130, 246, 0.1);
  border: 1px solid rgba(59, 130, 246, 0.4);
  color: #3b82f6;
}

.section {
  border: 1px solid var(--color-border);
  border-radius: 6px;
  padding: 0.75rem;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
}

.section-title {
  margin: 0;
  font-size: 0.85rem;
  font-weight: 600;
  color: var(--color-text);
}

.section-actions {
  display: flex;
  gap: 0.4rem;
}

.field-row {
  display: grid;
  grid-template-columns: 100px 1fr;
  align-items: center;
  gap: 0.5rem;
}

.field-row label {
  font-size: 0.78rem;
  color: var(--color-text-tertiary);
}

.input-field {
  padding: 0.25rem 0.5rem;
  background: var(--color-background-secondary);
  border: 1px solid var(--color-border);
  border-radius: 4px;
  color: var(--color-text);
  font-size: 0.78rem;
  width: 100%;
  box-sizing: border-box;
}

.input-select {
  padding: 0.25rem 0.5rem;
  background: var(--color-background-secondary);
  border: 1px solid var(--color-border);
  border-radius: 4px;
  color: var(--color-text);
  font-size: 0.78rem;
}

.polygon-input {
  padding: 0.4rem;
  background: var(--color-background-secondary);
  border: 1px solid var(--color-border);
  border-radius: 4px;
  color: var(--color-text);
  font-family: 'Courier New', monospace;
  font-size: 0.75rem;
  resize: vertical;
  width: 100%;
  box-sizing: border-box;
}

/* Board SVG preview */
.board-preview-container {
  display: flex;
  justify-content: center;
  padding: 0.5rem 0;
}

.board-preview {
  border-radius: 3px;
}

/* Components table */
.components-table-container,
.placement-table-container {
  max-height: 220px;
  overflow-y: auto;
}

.components-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.74rem;
}

.components-table th,
.components-table td {
  border: 1px solid var(--color-border);
  padding: 0.2rem 0.4rem;
  text-align: left;
  white-space: nowrap;
}

.components-table th {
  background: var(--color-background-secondary);
  font-weight: 600;
  color: var(--color-text-tertiary);
  font-size: 0.7rem;
  position: sticky;
  top: 0;
}

.row-fixed td {
  background: rgba(59, 130, 246, 0.06);
}

.mono {
  font-family: 'Courier New', monospace;
  color: var(--color-primary);
}

.val-cell {
  color: var(--color-text-secondary);
  max-width: 80px;
  overflow: hidden;
  text-overflow: ellipsis;
}

.pos-input {
  width: 50px;
  padding: 0.1rem 0.2rem;
  background: var(--color-background-secondary);
  border: 1px solid var(--color-border);
  border-radius: 3px;
  color: var(--color-text);
  font-size: 0.72rem;
}

.side-select {
  padding: 0.1rem 0.2rem;
  background: var(--color-background-secondary);
  border: 1px solid var(--color-border);
  border-radius: 3px;
  color: var(--color-text);
  font-size: 0.72rem;
}

.auto-place-hint {
  color: var(--color-text-tertiary);
  font-style: italic;
  font-size: 0.7rem;
  text-align: center;
}

.empty-hint {
  color: var(--color-text-tertiary);
  font-size: 0.75rem;
  margin: 0;
}

.hint {
  color: var(--color-text-tertiary);
  font-size: 0.73rem;
  margin: 0;
}

/* Add component row */
.add-comp-row {
  display: flex;
  gap: 0.4rem;
  align-items: center;
}

/* Buttons */
.btn {
  padding: 0.3rem 0.75rem;
  border-radius: 4px;
  border: none;
  cursor: pointer;
  font-size: 0.75rem;
  transition: opacity 0.15s;
  white-space: nowrap;
}

.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-primary {
  background: var(--color-primary);
  color: var(--color-text-on-primary);
}

.btn-secondary {
  background: var(--color-background-secondary);
  color: var(--color-text);
  border: 1px solid var(--color-border);
}

.btn-large {
  padding: 0.5rem 1.5rem;
  font-size: 0.85rem;
}

/* Action bar */
.action-bar {
  display: flex;
  justify-content: center;
  padding-bottom: 0.5rem;
}

/* Placement result */
.placement-errors {
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
  margin-bottom: 0.5rem;
}

.placement-error {
  font-size: 0.73rem;
  color: #ef4444;
  background: rgba(239, 68, 68, 0.07);
  padding: 0.2rem 0.5rem;
  border-radius: 3px;
}

.err-des {
  font-weight: 600;
}

.result-preview-container {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.4rem;
  padding: 0.5rem 0;
}

.result-preview {
  border-radius: 3px;
}

.legend {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  font-size: 0.7rem;
  color: var(--color-text-tertiary);
}

.legend-dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  margin-right: 3px;
}
</style>
