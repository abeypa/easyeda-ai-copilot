<template>
    <div class="circuit-agent-result">
        <div class="circuit-result-container">
            <!-- Project header -->
            <div class="circuit-info">
                <div class="project-header">
                    <div class="project-header-top">
                        <div style="word-wrap: break-word;">
                            <h3 class="project-name">{{ result?.circuit?.metadata?.project_name || 'Untitled Project' }}</h3>
                            <pre class="project-description">{{ result?.circuit?.metadata?.description }}</pre>
                        </div>
                    </div>
                </div>

                <!-- Assembly errors banner -->
                <AssemblyErrors v-if="assemblyErrors.length" :errors="assemblyErrors" />

                <!-- Structural blocks with per-block assemble buttons -->
                <div v-if="result?.circuit?.blocks?.length" class="blocks-section">
                    <h3>Structural blocks</h3>
                    <div class="blocks-grid">
                        <div v-for="block in result.circuit.blocks" :key="block.name" class="block-card">
                            <div class="block-header">
                                <span class="block-name">{{ block.name }}</span>
                                <button
                                    class="block-assemble-btn"
                                    :disabled="assemblingBlock === block.name"
                                    @click="assembleBlock(block.name)"
                                    title="Assemble only this block"
                                >
                                    <span v-if="assemblingBlock === block.name">⏳</span>
                                    <span v-else>▶</span>
                                    {{ assemblingBlock === block.name ? 'Placing...' : 'Assemble' }}
                                </button>
                            </div>
                            <pre class="block-description">{{ block.description }}</pre>
                            <div v-if="block.next_block_names?.length" class="next-blocks">
                                <span class="label">Related blocks:</span>
                                <div class="tags">
                                    <span v-for="nextBlock in block.next_block_names" :key="nextBlock" class="tag">
                                        {{ nextBlock }}
                                    </span>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Components with stock badges -->
                <div v-if="result?.circuit?.components?.length" class="components-section">
                    <h3>Components ({{ components.length }})</h3>
                    <div class="components-list">
                        <div v-for="(component, idx) in components" :key="idx" class="component-item">
                            <div class="component-header">
                                <span class="designator">{{ component.designator }}</span>
                                <span class="value">{{ component.value }}</span>
                                <!-- LCSC stock badge -->
                                <StockBadge :component="component" />
                            </div>
                            <div class="component-details">
                                <div class="detail-row">
                                    <span class="label">Block:</span>
                                    <span class="value">{{ component.block_name }}</span>
                                </div>
                                <div v-if="component.search_query" class="detail-row">
                                    <span class="label">Request:</span>
                                    <span class="value">{{ component.search_query }}</span>
                                </div>
                                <div v-if="component.part_uuid" class="detail-row">
                                    <span class="label">UUID:</span>
                                    <span class="value uuid">{{ component.part_uuid }}</span>
                                </div>
                                <!-- Show replacement info if component was swapped -->
                                <div v-if="component.replaced_from" class="detail-row replaced-info">
                                    <span class="label">Replaced:</span>
                                    <span class="value">{{ component.replaced_from }} → {{ component.part_uuid }}</span>
                                </div>
                            </div>
                            <div v-if="component.pins?.length" class="pins-section">
                                <table class="pins-table">
                                    <thead>
                                        <tr>
                                            <th>Pin</th>
                                            <th>Name</th>
                                            <th>Signal</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        <tr v-for="pin in component.pins"
                                            :key="`${component.designator}-${pin.pin_number}`">
                                            <td class="pin-number">{{ pin.pin_number }}</td>
                                            <td class="pin-name">{{ pin.name }}</td>
                                            <td class="pin-signal">{{ pin.signal_name }}</td>
                                        </tr>
                                    </tbody>
                                </table>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Block diagram (rendered as structured data, not PDF) -->
            <div v-if="result?.blockDiagram" class="block-diagram-section">
                <div class="section-header">
                    <h3>Block diagram</h3>
                    <button class="copy-json-btn" @click="copyBlockDiagram" :title="copyBdStatus">
                        {{ copyBdStatus === 'Copied!' ? '✓ Copied' : '📋 Copy JSON' }}
                    </button>
                </div>
                <pre class="block-diagram-json">{{ formatBlockDiagram(result.blockDiagram) }}</pre>
            </div>

            <!-- Export section -->
            <div v-if="result?.circuit?.components?.length" class="export-section">
                <h3>Export</h3>
                <div class="export-buttons">
                    <button class="export-btn" @click="exportBomCsv" title="Export BOM as CSV">
                        {{ bomExportStatus }}
                    </button>
                    <button class="export-btn" @click="exportGostBom" title="Export BOM in GOST format">
                        {{ gostExportStatus }}
                    </button>
                    <button class="export-btn" @click="exportSpiceNetlist" title="Export SPICE Netlist">
                        {{ spiceExportStatus }}
                    </button>
                </div>
            </div>

            <div class="project-footer">
                <div class="footer-buttons">
                    <IconButton class="assemble-button" variant="primary" @click="assembleCircuitHandler" icon="Play">
                        Assemble circuit
                    </IconButton>
                    <button class="copy-json-btn copy-full" @click="copyFullJson" :title="copyStatus">
                        {{ copyStatus === 'Copied!' ? '✓ Copied' : '📋 Copy Full JSON' }}
                    </button>
                </div>
            </div>
        </div>
    </div>
</template>

<script setup lang="ts">
import { computed, onMounted, defineComponent, h, ref } from 'vue';
import IconButton from '../../shared/IconButton.vue';
import AssemblyErrors from '../AssemblyErrors.vue';
import { InlineButton } from '../../../types/inline-button';
import { assembleCircuit } from '../../../eda/assemble-circuit';
import { resolveComponentUuids } from '../../../eda/resolve-uuids';
import { showToastMessage } from '../../../eda/utils';
import { generateBomCsv, generateGostBomCsv, downloadFile } from '../../../utils/export/bom-export';
import { generateSpiceNetlist, downloadSpiceNetlist } from '../../../utils/export/spice-export';

// Inline StockBadge sub-component
const StockBadge = defineComponent({
    props: { component: Object },
    setup(props) {
        return () => {
            const c = props.component as any;
            if (!c) return null;

            const stock = c.stock_count;
            const stockStatus = c.stock_status; // 'in_stock' | 'low_stock' | 'out_of_stock'

            if (stock === undefined && !stockStatus) return null;

            let cls = 'stock-badge';
            let text = '';

            if (stockStatus === 'out_of_stock' || stock === 0) {
                cls += ' stock-out';
                text = c.replaced_with
                    ? `Out of Stock — replaced with ${c.replaced_with}`
                    : 'Out of Stock';
            } else if (stockStatus === 'low_stock' || (typeof stock === 'number' && stock < 100)) {
                cls += ' stock-low';
                text = `Low Stock${typeof stock === 'number' ? ` (${stock})` : ''}`;
            } else {
                cls += ' stock-ok';
                text = `In Stock${typeof stock === 'number' ? ` (${stock})` : ''}`;
            }

            return h('span', { class: cls }, text);
        };
    },
});

const props = defineProps<{ result: any }>();
const emit = defineEmits<{ 'inline-buttons': [InlineButton[]] }>();

const components = computed(() =>
    (props.result?.circuit?.components || []).filter((comp: any) => !['GND', 'VCC'].includes(comp.part_uuid))
);

// v2.3.7: runtime errors captured during the last assembleCircuit() call.
// Merged with backend-supplied errors so the AssemblyErrors banner shows
// both stock/UUID notices AND live placement/wire failures from the SDK
// (which would otherwise vanish with the disappearing toasts).
const runtimeAssemblyErrors = ref<any[]>([]);

const assemblyErrors = computed(() => {
    const fromResult = props.result?.assembly_errors || props.result?.errors || [];
    return [...fromResult, ...runtimeAssemblyErrors.value];
});

const assemblingBlock = ref<string | null>(null);
const copyStatus = ref('Copy Full JSON');
const copyBdStatus = ref('Copy JSON');
const bomExportStatus = ref('📄 BOM (CSV)');
const gostExportStatus = ref('🏭 GOST BOM');
const spiceExportStatus = ref('⚡ SPICE Netlist');

function formatBlockDiagram(bd: any): string {
    try {
        return JSON.stringify(bd, null, 2);
    } catch {
        return String(bd);
    }
}

async function copyFullJson() {
    try {
        const json = JSON.stringify(props.result, null, 2);
        await navigator.clipboard.writeText(json);
        copyStatus.value = 'Copied!';
        setTimeout(() => { copyStatus.value = 'Copy Full JSON'; }, 2000);
    } catch {
        // Fallback for iframe context
        const textarea = document.createElement('textarea');
        textarea.value = JSON.stringify(props.result, null, 2);
        document.body.appendChild(textarea);
        textarea.select();
        document.execCommand('copy');
        document.body.removeChild(textarea);
        copyStatus.value = 'Copied!';
        setTimeout(() => { copyStatus.value = 'Copy Full JSON'; }, 2000);
    }
}

async function copyBlockDiagram() {
    try {
        const json = JSON.stringify(props.result?.blockDiagram, null, 2);
        await navigator.clipboard.writeText(json);
        copyBdStatus.value = 'Copied!';
        setTimeout(() => { copyBdStatus.value = 'Copy JSON'; }, 2000);
    } catch {
        const textarea = document.createElement('textarea');
        textarea.value = JSON.stringify(props.result?.blockDiagram, null, 2);
        document.body.appendChild(textarea);
        textarea.select();
        document.execCommand('copy');
        document.body.removeChild(textarea);
        copyBdStatus.value = 'Copied!';
        setTimeout(() => { copyBdStatus.value = 'Copy JSON'; }, 2000);
    }
}

function exportBomCsv() {
    if (!props.result?.circuit?.components?.length) return;
    const items = props.result.circuit.components.map((c: any) => ({
        designator: c.designator,
        value: c.value,
        search_query: c.search_query || c.value,
        part_uuid: c.part_uuid,
        block_name: c.block_name,
        pins: c.pins?.length || 0,
    }));
    const csv = generateBomCsv(items);
    const projectName = props.result?.circuit?.metadata?.project_name?.replace(/\s+/g, '_') || 'circuit';
    downloadFile(csv, `${projectName}_BOM.csv`);
    bomExportStatus.value = '\u2713 BOM Exported';
    setTimeout(() => { bomExportStatus.value = '\ud83d\udcc4 BOM (CSV)'; }, 3000);
}

function exportGostBom() {
    if (!props.result?.circuit?.components?.length) return;
    const items = props.result.circuit.components.map((c: any) => ({
        designator: c.designator,
        value: c.value,
        search_query: c.search_query || c.value,
        part_uuid: c.part_uuid,
        block_name: c.block_name,
        pins: c.pins?.length || 0,
    }));
    const csv = generateGostBomCsv(items);
    const projectName = props.result?.circuit?.metadata?.project_name?.replace(/\s+/g, '_') || 'circuit';
    downloadFile(csv, `${projectName}_BOM_GOST.csv`);
    gostExportStatus.value = '\u2713 GOST Exported';
    setTimeout(() => { gostExportStatus.value = '\ud83c\udfed GOST BOM'; }, 3000);
}

function exportSpiceNetlist() {
    if (!props.result?.circuit?.components?.length) return;
    const comps = props.result.circuit.components.map((c: any) => ({
        designator: c.designator,
        value: c.value,
        pins: (c.pins || []).map((p: any) => ({
            pin_number: p.pin_number,
            name: p.name,
            signal_name: p.signal_name,
        })),
        block_name: c.block_name,
    }));
    const projectName = props.result?.circuit?.metadata?.project_name || 'circuit';
    downloadSpiceNetlist(comps, projectName);
    spiceExportStatus.value = '\u2713 SPICE Exported';
    setTimeout(() => { spiceExportStatus.value = '\u26a1 SPICE Netlist'; }, 3000);
}

/**
 * Assemble only components in a single block
 */
async function assembleBlock(blockName: string) {
    if (!props.result?.circuit) return;
    assemblingBlock.value = blockName;

    try {
        const circuit = props.result.circuit;

        // Filter components for this block only
        const blockComponents = circuit.components.filter(
            (c: any) => c.block_name === blockName
        );

        if (!blockComponents.length) {
            showToastMessage(`No components found in block: ${blockName}`, 'error');
            return;
        }

        // Get edges connecting only block components
        const blockDesignators = new Set(blockComponents.map((c: any) => c.designator));
        const blockEdges = (circuit.edges || []).filter((edge: any) =>
            edge.sections?.some((s: any) => {
                const [sd] = (s.incomingShape || '').split('_pin_');
                const [td] = (s.outgoingShape || '').split('_pin_');
                return blockDesignators.has(sd) || blockDesignators.has(td);
            })
        );

        // Find the block's rect
        const blockRects = (circuit.blocks_rect || []).filter((r: any) =>
            r.name === blockName || r.name === 'block___v_root__'
        );

        const partialCircuit = {
            ...circuit,
            components: blockComponents,
            edges: blockEdges,
            blocks: circuit.blocks?.filter((b: any) => b.name === blockName) || [],
            blocks_rect: blockRects,
            added_net: (circuit.added_net || []).filter((n: any) => blockDesignators.has(n.designator)),
            rm_components: [],
        };

        // Resolve missing LCSC UUIDs before assembly
        showToastMessage('Resolving component UUIDs...', 'info');
        await resolveComponentUuids(partialCircuit.components);
        const runtimeErrors = await assembleCircuit(partialCircuit);
        if (runtimeErrors?.length) {
            runtimeAssemblyErrors.value = runtimeErrors.map(e => ({
                component: e.component,
                message: e.message,
                severity: e.severity,
            }));
        }
        showToastMessage(`Block "${blockName}" assembled`, 'success');
    } catch (err) {
        showToastMessage(`Failed to assemble block: ${(err as Error).message}`, 'error');
    } finally {
        assemblingBlock.value = null;
    }
}

async function assembleCircuitHandler() {
    if (!props.result?.circuit) return;
    showToastMessage('Resolving component UUIDs...', 'info');
    // Resolve missing LCSC UUIDs before assembly
    await resolveComponentUuids(props.result.circuit.components);
    // v2.3.7: capture runtime errors so they persist in the chat panel
    // (the AssemblyErrors banner) instead of vanishing with the toast.
    const runtimeErrors = await assembleCircuit(props.result.circuit);
    if (runtimeErrors?.length) {
        runtimeAssemblyErrors.value = runtimeErrors.map(e => ({
            component: e.component,
            message: e.message,
            severity: e.severity,
        }));
    } else {
        runtimeAssemblyErrors.value = [];
    }
}

onMounted(() => {
    emit('inline-buttons', [{
        icon: 'Play',
        text: 'Assemble circuit',
        handler: () => assembleCircuitHandler()
    }]);
});
</script>

<style scoped>
.circuit-result-container {
    display: flex;
    flex-direction: column;
}

.circuit-info {
    display: flex;
    flex-direction: column;
    gap: 1.5rem;
    min-width: 0;
}

.project-footer {
    padding-top: 1rem;
}

.project-header {
    border-bottom: 1px solid var(--color-border);
    padding-bottom: 1rem;
}

.project-header-top {
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    align-items: flex-start;
    gap: 1rem;
}

.assemble-button {
    padding-right: 1rem;
}

.project-name {
    margin: 0 0 0.5rem 0;
    color: var(--color-text-primary);
}

.project-description {
    margin: 0;
    font-size: 0.9rem;
    color: var(--color-text-secondary);
    background: transparent;
    border: none;
    padding: 0;
}

/* Blocks */
.blocks-section h3,
.components-section h3 {
    margin-top: 0;
    margin-bottom: 1rem;
    font-size: 1.1rem;
    color: var(--color-text-primary);
}

.blocks-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
    gap: 1rem;
    max-height: 260px;
    overflow-y: auto;
}

.block-card {
    background: var(--color-background);
    border: 1px solid var(--color-border);
    border-radius: 0.375rem;
    padding: 0.75rem;
    transition: background-color 0.2s;
}

.block-card:hover {
    background: var(--color-surface-hover);
}

.block-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 0.5rem;
    gap: 0.5rem;
}

.block-name {
    font-weight: 600;
    color: var(--color-primary);
    font-size: 0.9rem;
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

/* Per-block assemble button */
.block-assemble-btn {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 2px 8px;
    font-size: 0.7rem;
    background: var(--color-primary);
    color: var(--color-text-on-primary);
    border: none;
    border-radius: 4px;
    cursor: pointer;
    white-space: nowrap;
    transition: opacity 0.15s;
    flex-shrink: 0;
}

.block-assemble-btn:disabled {
    opacity: 0.6;
    cursor: not-allowed;
}

.block-assemble-btn:hover:not(:disabled) {
    opacity: 0.85;
}

.block-description {
    background: transparent;
    border: none;
    margin: 0;
    padding: 0;
    font-size: 0.8rem;
    color: var(--color-text-secondary);
    white-space: pre-wrap;
    word-break: break-word;
}

.next-blocks {
    margin-top: 0.75rem;
    padding-top: 0.75rem;
    border-top: 1px solid var(--color-border);
}

.next-blocks .label {
    display: block;
    font-size: 0.8rem;
    color: var(--color-text-tertiary);
    margin-bottom: 0.5rem;
}

.tags {
    display: flex;
    flex-wrap: wrap;
    gap: 0.25rem;
}

.tag {
    display: inline-block;
    background: var(--color-primary-subtle);
    color: var(--color-primary);
    padding: 0.25rem 0.5rem;
    border-radius: 0.25rem;
    font-size: 0.75rem;
}

/* Components */
.components-list {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
    gap: 1rem;
    max-height: 260px;
    overflow-y: auto;
    padding-right: 0.5rem;
}

.component-item {
    background: var(--color-background);
    border: 1px solid var(--color-border);
    border-radius: 0.375rem;
    padding: 0.75rem;
    transition: background-color 0.2s;
}

.component-item:hover {
    background: var(--color-surface-hover);
}

.component-header {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
    margin-bottom: 0.5rem;
    align-items: baseline;
}

.designator {
    font-weight: 600;
    color: var(--color-text-primary);
    min-width: 40px;
}

.component-header .value {
    color: var(--color-primary);
    font-size: 0.85rem;
    flex: 1;
}

/* Stock badges */
:deep(.stock-badge) {
    font-size: 0.65rem;
    padding: 1px 6px;
    border-radius: 10px;
    font-weight: 600;
    white-space: nowrap;
}

:deep(.stock-ok) {
    background: rgba(34, 197, 94, 0.15);
    color: #16a34a;
}

:deep(.stock-low) {
    background: rgba(234, 179, 8, 0.15);
    color: #ca8a04;
}

:deep(.stock-out) {
    background: rgba(239, 68, 68, 0.15);
    color: #dc2626;
}

.component-details {
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
    font-size: 0.8rem;
    margin-bottom: 0.5rem;
}

.detail-row {
    display: grid;
    grid-template-columns: 60px 1fr;
    gap: 0.5rem;
    align-items: center;
}

.detail-row .label {
    color: var(--color-text-tertiary);
    font-weight: 500;
}

.detail-row .value {
    color: var(--color-text-secondary);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.detail-row.replaced-info .value {
    color: #f59e0b;
    font-style: italic;
}

.uuid {
    font-family: 'Courier New', monospace;
    font-size: 0.72rem;
}

.pins-section {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
    padding-top: 0.5rem;
    border-top: 1px solid var(--color-border);
    margin-top: 0.5rem;
}

.pins-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.78rem;
    margin-top: 0.5rem;
}

.pins-table th,
.pins-table td {
    border: 1px solid var(--color-border);
    padding: 0.25rem 0.5rem;
    text-align: left;
}

.pins-table th {
    background: var(--color-background-secondary);
    font-weight: 600;
    color: var(--color-text-primary);
    font-size: 0.73rem;
}

.pins-table td.pin-number {
    font-weight: 600;
    color: var(--color-primary);
}

.pins-table td.pin-name {
    color: var(--color-text-primary);
}

.pins-table td.pin-signal {
    color: var(--color-text-tertiary);
    font-size: 0.72rem;
}

/* Block diagram section */
.block-diagram-section {
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
    margin-top: 15px;
}

.section-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
}

.section-header h3 {
    margin: 0;
    font-size: 1.1rem;
    color: var(--color-text-primary);
}

.block-diagram-json {
    background: var(--color-background-secondary);
    border: 1px solid var(--color-border);
    border-radius: 0.375rem;
    padding: 0.75rem;
    font-size: 0.72rem;
    max-height: 200px;
    overflow: auto;
    white-space: pre-wrap;
    word-break: break-word;
    color: var(--color-text-secondary);
}

/* Copy JSON button */
.copy-json-btn {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 4px 10px;
    font-size: 0.72rem;
    background: var(--color-background-secondary);
    color: var(--color-text-secondary);
    border: 1px solid var(--color-border);
    border-radius: 4px;
    cursor: pointer;
    white-space: nowrap;
    transition: all 0.15s;
}

.copy-json-btn:hover {
    background: var(--color-surface-hover);
    color: var(--color-text-primary);
}

.copy-json-btn.copy-full {
    background: transparent;
    border: 1px solid var(--color-border);
}

.footer-buttons {
    display: flex;
    gap: 0.75rem;
    align-items: center;
    flex-wrap: wrap;
}

/* Export section */
.export-section {
    padding-top: 1rem;
    border-top: 1px solid var(--color-border);
}

.export-section h3 {
    margin: 0 0 0.75rem 0;
    font-size: 1.1rem;
    color: var(--color-text-primary);
}

.export-buttons {
    display: flex;
    gap: 0.5rem;
    flex-wrap: wrap;
    align-items: center;
}

.export-btn {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 4px 10px;
    font-size: 0.72rem;
    background: var(--color-background-secondary);
    color: var(--color-text-secondary);
    border: 1px solid var(--color-border);
    border-radius: 4px;
    cursor: pointer;
    white-space: nowrap;
    transition: all 0.15s;
    font-family: inherit;
}

.export-btn:hover {
    background: var(--color-surface-hover);
    color: var(--color-text-primary);
    border-color: var(--color-primary);
}
</style>
