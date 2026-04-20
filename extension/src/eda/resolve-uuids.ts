/**
 * Resolve LCSC part UUIDs for components using EasyEDA's built-in search.
 * Called before assembly to fill in missing part_uuid values.
 *
 * This runs in the extension main thread where `eda.lib_Device.search()` is
 * available.  The backend may return components with `part_uuid: null` and a
 * `search_query` field — this function fills in the real UUID so that
 * `eda.sch_PrimitiveComponent.create()` can find the component in the LCSC
 * library.
 *
 * Uses a multi-strategy search approach: tries the component value first,
 * then the first word of the search query (often the part number), then
 * the full search query string.
 *
 * Also stores `_libraryUuid` on the component so that createComponet can
 * use the correct library when placing (instead of always assuming 'lcsc').
 */

import type { CircuitAssembly } from "../types/circuit";

export async function resolveComponentUuids(
    components: CircuitAssembly['components'],
): Promise<void> {
    let resolvedCount = 0;
    let failedCount = 0;
    const failedDesignators: string[] = [];

    eda.sys_Message.showToastMessage(
        `Resolving ${components.length} component UUIDs from EasyEDA library...`,
        ESYS_ToastMessageType.INFO
    );

    for (const comp of components) {
        // Already resolved — skip
        if (comp.part_uuid && comp.part_uuid.length === 32) { resolvedCount++; continue; }
        // Special markers — skip
        if (comp.part_uuid === 'GND' || comp.part_uuid === 'VCC') continue;

        const searchQuery = (comp as any).search_query || '';
        const value = comp.value || '';

        // Try multiple search strategies, from most specific to least
        const queries: string[] = [];

        // Strategy 1: Just the part number/value (e.g., "STM32G431CBU6", "LM2596S-ADJ", "AMS1117-3.3")
        if (value) queries.push(value);

        // Strategy 2: First word of search_query (often the actual part number)
        if (searchQuery && searchQuery !== value) {
            const partName = searchQuery.split(' ')[0];
            if (partName && partName !== value) queries.push(partName);
            queries.push(searchQuery);
        }

        let found = false;
        for (const query of queries) {
            if (!query) continue;
            try {
                const devices = await eda.lib_Device.search(query);
                if (devices && devices.length > 0) {
                    // Find best match — prefer LCSC library components
                    const match = devices.find((d: any) =>
                        d.supplierId === query ||
                        d.manufacturerId === query ||
                        d.name === query
                    ) || devices.find((d: any) =>
                        d.name?.toLowerCase().includes(value.toLowerCase())
                    ) || devices[0];

                    if (match?.uuid) {
                        (comp as any).part_uuid = match.uuid;
                        // Store libraryUuid so createComponet can use the correct library
                        (comp as any)._libraryUuid = match.libraryUuid || 'lcsc';
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
            failedDesignators.push(comp.designator);
            console.warn(`[AI Copilot] Could not resolve UUID for ${comp.designator} (${value}). Tried: ${queries.join(', ')}`);
        }
    }

    console.log(`[AI Copilot] UUID resolution complete: ${resolvedCount} resolved, ${failedCount} unresolved`);

    if (resolvedCount > 0 && failedCount === 0) {
        eda.sys_Message.showToastMessage(
            `All ${resolvedCount} components resolved successfully!`,
            ESYS_ToastMessageType.SUCCESS
        );
    } else if (resolvedCount > 0) {
        eda.sys_Message.showToastMessage(
            `${resolvedCount} resolved, ${failedCount} not found: ${failedDesignators.slice(0, 5).join(', ')}${failedCount > 5 ? '...' : ''}`,
            ESYS_ToastMessageType.WARNING
        );
    } else {
        eda.sys_Message.showToastMessage(
            `Could not find any components in EasyEDA library. Check if LCSC libraries are enabled.`,
            ESYS_ToastMessageType.ERROR
        );
    }
}
