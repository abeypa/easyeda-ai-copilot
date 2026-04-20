/**
 * Resolve LCSC part UUIDs for components using EasyEDA's built-in search.
 * Called before assembly to fill in missing part_uuid values.
 *
 * NOTE: In the iframe context, `eda.lib_Device.search()` may not be directly
 * available. The primary UUID resolution happens in the main extension thread
 * (src/eda/assemble.ts → src/eda/resolve-uuids.ts) which runs before component
 * placement. This iframe-side utility serves as an additional pre-check and
 * will gracefully skip if the SDK search is not available.
 *
 * Uses a multi-strategy search approach: tries the component value first,
 * then the first word of the search query (often the part number), then
 * the full search query string.
 */

import { isEasyEda } from './utils';

interface ResolvableComponent {
    designator: string;
    value: string;
    search_query?: string;
    part_uuid?: string | null;
}

export async function resolveComponentUuids(
    components: ResolvableComponent[],
): Promise<void> {
    if (!isEasyEda()) return;

    // Check if eda.lib_Device.search is available in this context
    if (typeof eda?.lib_Device?.search !== 'function') {
        // Not available in iframe — main thread will handle it during assembly
        return;
    }

    let resolvedCount = 0;
    let failedCount = 0;

    for (const comp of components) {
        if (comp.part_uuid && comp.part_uuid.length === 32) { resolvedCount++; continue; } // Already resolved
        if (comp.part_uuid === 'GND' || comp.part_uuid === 'VCC') continue; // Special markers

        const searchQuery = comp.search_query || '';
        const value = comp.value || '';

        // Try multiple search strategies, from most specific to least
        const queries: string[] = [];

        // Strategy 1: Just the part number/value (e.g., "STM32G431CBU6", "LM2596S-ADJ")
        if (value) queries.push(value);

        // Strategy 2: Value + key package info extracted from search_query
        if (searchQuery && searchQuery !== value) {
            // Extract just the part name from longer search queries
            const partName = searchQuery.split(' ')[0]; // First word is usually the part number
            if (partName && partName !== value) queries.push(partName);
            queries.push(searchQuery);
        }

        let found = false;
        for (const query of queries) {
            if (!query) continue;
            try {
                const devices = await eda.lib_Device.search(query);
                if (devices && devices.length > 0) {
                    // Find best match
                    const match = devices.find((d: any) =>
                        d.name === query ||
                        d.supplierId === query ||
                        d.manufacturerId === query ||
                        d.name?.toLowerCase().includes(value.toLowerCase())
                    ) || devices[0];

                    if (match?.uuid) {
                        comp.part_uuid = match.uuid;
                        resolvedCount++;
                        found = true;
                        break;
                    }
                }
            } catch (err) {
                // continue to next strategy
            }
        }

        if (!found) {
            failedCount++;
            console.warn(`[AI Copilot] Could not resolve UUID for ${comp.designator} (${value}). Tried: ${queries.join(', ')}`);
        }
    }

    console.log(`[AI Copilot] UUID resolution: ${resolvedCount} resolved, ${failedCount} unresolved`);
}
