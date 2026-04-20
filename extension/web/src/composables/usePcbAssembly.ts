/**
 * usePcbAssembly.ts
 * Manages PCB assembly state: board boundary, fixed parts, and placement requests.
 */
import { ref, computed } from 'vue';
import { getApiUrl, fetchEda } from '../api/index';
import { isEasyEda } from '../eda/utils';

export interface BoundaryRect {
    type: 'rectangle';
    width: number;  // mm
    height: number; // mm
}

export interface BoundaryPolygon {
    type: 'polygon';
    points: Array<{ x: number; y: number }>; // mm
}

export type BoardBoundary = BoundaryRect | BoundaryPolygon;

export interface FixedPart {
    designator: string;
    x: number;   // mm
    y: number;   // mm
    side: 'top' | 'bottom';
    rotation: number; // degrees
    fixed: boolean;
}

export interface SchematicComponent {
    designator: string;
    value: string;
    footprint?: string;
    part_uuid?: string;
}

export interface PcbPlacementResult {
    placements: Array<{
        designator: string;
        x: number;
        y: number;
        rotation: number;
        side: 'top' | 'bottom';
    }>;
    errors?: Array<{ designator: string; message: string }>;
}

export function usePcbAssembly() {
    // Board boundary state
    const boundaryType = ref<'rectangle' | 'polygon'>('rectangle');
    const boundaryWidth = ref<number>(100);
    const boundaryHeight = ref<number>(80);
    const polygonPoints = ref<Array<{ x: number; y: number }>>([
        { x: 0, y: 0 }, { x: 100, y: 0 }, { x: 100, y: 80 }, { x: 0, y: 80 }
    ]);

    // Fixed parts (user-pinned components)
    const fixedParts = ref<FixedPart[]>([]);

    // Components from schematic BOM (loaded from EasyEDA or entered manually)
    const schematicComponents = ref<SchematicComponent[]>([]);

    // Placement result from backend
    const placementResult = ref<PcbPlacementResult | null>(null);

    // UI state
    const isLoading = ref(false);
    const error = ref<string | null>(null);
    const status = ref<string>('');

    const boundary = computed<BoardBoundary>(() => {
        if (boundaryType.value === 'rectangle') {
            return { type: 'rectangle', width: boundaryWidth.value, height: boundaryHeight.value };
        }
        return { type: 'polygon', points: polygonPoints.value };
    });

    /** Load components from the EasyEDA schematic BOM */
    async function loadFromSchematic() {
        if (!isEasyEda()) {
            error.value = 'EasyEDA Pro not detected';
            return;
        }

        try {
            status.value = 'Reading schematic BOM...';
            const bomData = await eda.sch_ManufactureData.getBomFile(
                'bom.csv', 'csv', undefined, undefined,
                ['Number'],
                ['Designator', 'Value', 'Footprint', 'Manufacturer Part']
            );

            if (!bomData) {
                error.value = 'Could not read BOM from schematic';
                return;
            }

            const text = await bomData.text();
            const lines = text.trim().split('\n');
            const headers = lines[0].split('\t').map((h: string) => h.trim());

            const components: SchematicComponent[] = [];
            for (let i = 1; i < lines.length; i++) {
                const cells = lines[i].split('\t').map((c: string) => c.trim());
                const row: Record<string, string> = {};
                headers.forEach((h: string, idx: number) => { row[h] = cells[idx] || ''; });

                if (row['Designator']) {
                    components.push({
                        designator: row['Designator'],
                        value: row['Value'] || '',
                        footprint: row['Footprint'] || '',
                        part_uuid: row['Manufacturer Part'] || '',
                    });
                }
            }

            schematicComponents.value = components;

            // Initialize fixed parts list from components (all unfixed by default)
            fixedParts.value = components.map(c => ({
                designator: c.designator,
                x: 0,
                y: 0,
                side: 'top' as const,
                rotation: 0,
                fixed: false,
            }));

            status.value = `Loaded ${components.length} components from schematic`;
            error.value = null;
        } catch (err) {
            error.value = err instanceof Error ? err.message : 'Failed to load schematic';
        } finally {
            isLoading.value = false;
        }
    }

    /** Add a manual component to the list */
    function addComponent(designator: string, value: string = '') {
        if (!designator.trim()) return;
        if (schematicComponents.value.some(c => c.designator === designator)) return;

        schematicComponents.value.push({ designator, value });
        fixedParts.value.push({ designator, x: 0, y: 0, side: 'top', rotation: 0, fixed: false });
    }

    /** Toggle fixed status for a part */
    function toggleFixed(designator: string, fixed: boolean) {
        const part = fixedParts.value.find(p => p.designator === designator);
        if (part) part.fixed = fixed;
    }

    /** Update fixed position for a part */
    function updateFixedPosition(designator: string, x: number, y: number, rotation = 0, side: 'top' | 'bottom' = 'top') {
        const part = fixedParts.value.find(p => p.designator === designator);
        if (part) {
            part.x = x;
            part.y = y;
            part.rotation = rotation;
            part.side = side;
        }
    }

    /**
     * Call the backend /v2/chat with action:"pcb_place" to get an AI-assisted
     * component placement plan.
     */
    async function requestPlacement() {
        if (!schematicComponents.value.length) {
            error.value = 'No components to place. Load from schematic first.';
            return;
        }

        isLoading.value = true;
        error.value = null;
        status.value = 'Requesting PCB placement from AI...';
        placementResult.value = null;

        try {
            const apiUrl = getApiUrl();

            const body = {
                action: 'pcb_place',
                components: schematicComponents.value,
                boundary: boundary.value,
                fixed_parts: fixedParts.value.filter(p => p.fixed).map(p => ({
                    designator: p.designator,
                    x: p.x,
                    y: p.y,
                    rotation: p.rotation,
                    side: p.side,
                })),
                constraints: {
                    min_spacing: 0.5,
                },
            };

            const res = await fetchEda(apiUrl + '/v2/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });

            if (!res.ok) {
                const text = await res.text();
                throw new Error(`Backend error ${res.status}: ${text}`);
            }

            const data = await res.json();

            // Backend may return placements directly or inside result
            const placements = data.placements || data.result?.placements || [];
            placementResult.value = {
                placements,
                errors: data.errors || data.result?.errors || [],
            };

            status.value = `Placement calculated: ${placements.length} components`;
        } catch (err) {
            error.value = err instanceof Error ? err.message : 'Placement request failed';
            status.value = '';
        } finally {
            isLoading.value = false;
        }
    }

    /**
     * Apply placement result to EasyEDA PCB editor.
     * Calls eda.placePcbComponents() registered by the extension main thread.
     */
    async function applyToEda() {
        if (!placementResult.value?.placements.length) {
            error.value = 'No placement result to apply';
            return;
        }

        if (!isEasyEda()) {
            error.value = 'EasyEDA Pro not detected';
            return;
        }

        isLoading.value = true;
        status.value = 'Applying placement to PCB...';
        error.value = null;

        try {
            if (typeof eda.placePcbComponents !== 'function') {
                throw new Error('PCB placement API not available — open extension in EasyEDA Pro PCB editor');
            }

            const result = await eda.placePcbComponents(placementResult.value.placements);
            status.value = `Applied: ${result.placed.length} placed, ${result.failed.length} failed`;

            if (result.failed.length) {
                error.value = `Failed to place: ${result.failed.map(f => `${f.designator} (${f.error})`).join(', ')}`;
            }
        } catch (err) {
            error.value = err instanceof Error ? err.message : 'Failed to apply placement';
            status.value = '';
        } finally {
            isLoading.value = false;
        }
    }

    return {
        // Boundary
        boundaryType,
        boundaryWidth,
        boundaryHeight,
        polygonPoints,
        boundary,

        // Parts
        fixedParts,
        schematicComponents,

        // Result
        placementResult,

        // UI state
        isLoading,
        error,
        status,

        // Actions
        loadFromSchematic,
        addComponent,
        toggleFixed,
        updateFixedPosition,
        requestPlacement,
        applyToEda,
    };
}
