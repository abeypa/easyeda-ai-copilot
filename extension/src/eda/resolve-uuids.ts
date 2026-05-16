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

/** Matches LCSC supplier IDs like C2898701, C404270 (C + 5-8 digits). */
const LCSC_RE = /\bC\d{5,8}\b/g;

/** Extract all LCSC C-numbers found in a string. */
function extractLcscNumbers(s: string): string[] {
    return [...(s.matchAll(LCSC_RE))].map(m => m[0]);
}

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
        // Special markers — skip
        if (comp.part_uuid === 'GND' || comp.part_uuid === 'VCC') continue;

        const searchQuery = (comp as any).search_query || '';
        const value = comp.value || '';

        // v2.4.4: If the backend already resolved both uuid AND libraryUuid
        // (via jlcsearch.tscircuit.com), skip local EasyEDA search entirely.
        // The backend uses deterministic MD5-based UUIDs from LCSC C-numbers,
        // which are the same UUIDs EasyEDA uses internally.
        const hasResolvedUuid = comp.part_uuid && comp.part_uuid.length === 32;
        const hasLibUuid = !!(comp as any)._libraryUuid;
        if (hasResolvedUuid && hasLibUuid) {
            resolvedCount++;
            continue;
        }

        // Preserve the LLM-provided uuid as a last-resort fallback.
        const fallbackUuid = hasResolvedUuid ? comp.part_uuid : undefined;

        // Build search query list from most-specific to least-specific.
        const queries: string[] = [];

        // Strategy 0 (highest priority): LCSC C-numbers extracted from search_query or value.
        // These match directly on supplierId so they are the most reliable lookup.
        const lcscNumbers = [
            ...extractLcscNumbers(searchQuery),
            ...extractLcscNumbers(value),
        ];
        // De-duplicate while preserving order
        for (const lcsc of lcscNumbers) {
            if (!queries.includes(lcsc)) queries.push(lcsc);
        }

        // Strategy 1: Component value (e.g., "STM32G431CBU6", "AMS1117-3.3")
        if (value && !queries.includes(value)) queries.push(value);

        // Strategy 2: First word of search_query (often the bare part number)
        if (searchQuery && searchQuery !== value) {
            const partName = searchQuery.split(' ')[0];
            if (partName && !queries.includes(partName)) queries.push(partName);
            // Strategy 3: Full search_query
            if (!queries.includes(searchQuery)) queries.push(searchQuery);
        }

        let found = false;
        for (const query of queries) {
            if (!query) continue;

            // For LCSC C-number queries we want an exact supplierId match.
            const isLcscQuery = /^C\d{5,8}$/.test(query);

            try {
                const devices = await eda.lib_Device.search(query);
                if (devices && devices.length > 0) {
                    // Prefer exact supplier/manufacturer/name match, then name substring,
                    // finally the first result.
                    const match =
                        devices.find((d: any) =>
                            d.supplierId === query ||
                            d.manufacturerId === query ||
                            d.name === query
                        ) ||
                        // When the query is NOT an LCSC number, allow a name-substring match.
                        (!isLcscQuery
                            ? devices.find((d: any) =>
                                  d.name?.toLowerCase().includes(value.toLowerCase())
                              )
                            : undefined) ||
                        // For LCSC queries only use devices[0] if supplierId matches.
                        (isLcscQuery
                            ? devices.find((d: any) => d.supplierId === query)
                            : devices[0]);

                    if (match?.uuid) {
                        (comp as any).part_uuid = match.uuid;
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
            if (fallbackUuid) {
                // Keep the LLM-provided uuid; placeComponent will try several
                // library UUIDs. This may still succeed if the uuid is valid.
                (comp as any).part_uuid = fallbackUuid;
                resolvedCount++;
                console.warn(
                    `[AI Copilot] Search failed for ${comp.designator}; using LLM-provided uuid ${fallbackUuid} as fallback.`
                );
            } else {
                failedCount++;
                failedDesignators.push(comp.designator);
                console.warn(
                    `[AI Copilot] Could not resolve UUID for ${comp.designator} (${value}). ` +
                    `Tried: ${queries.join(', ')}`
                );
            }
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
