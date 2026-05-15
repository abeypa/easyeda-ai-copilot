/**
 * PCB Placement API wrapper
 * Uses EasyEDA Pro's PCB_PrimitiveComponent APIs to place and move components on the PCB.
 */

export interface PcbPlacementItem {
    /** Designator, e.g. "U1", "R1" */
    designator: string;
    /** X position in mm */
    x: number;
    /** Y position in mm */
    y: number;
    /** Rotation in degrees (0-360) */
    rotation?: number;
    /** Which side of the board */
    side?: 'top' | 'bottom';
}

/**
 * Place or move a list of components on the PCB.
 * This function runs in the extension main thread where EDA APIs are available.
 */
export async function placePcbComponents(placements: PcbPlacementItem[]): Promise<{
    placed: string[];
    failed: Array<{ designator: string; error: string }>;
}> {
    const placed: string[] = [];
    const failed: Array<{ designator: string; error: string }> = [];

    // Get all existing PCB components so we can look up by designator
    let existingComponents: IPCB_PrimitiveComponent[] = [];
    try {
        // @ts-ignore — API might not be available in all contexts
        existingComponents = await eda.pcb_PrimitiveComponent?.getAll?.() ?? [];
    } catch (_) {
        existingComponents = [];
    }

    const existingMap = new Map<string, IPCB_PrimitiveComponent>();
    for (const comp of existingComponents) {
        try {
            const designator = comp.getState_Designator?.();
            if (designator) existingMap.set(designator, comp);
        } catch (_) { /* skip */ }
    }

    for (const placement of placements) {
        try {
            const { designator, x, y, rotation = 0, side = 'top' } = placement;

            // Convert mm to EasyEDA internal units (1 mil = 0.0254mm, but EasyEDA Pro uses 10-mil units)
            // EasyEDA Pro PCB coordinate unit: 1 unit = 10 mil = 0.254mm
            const toUnits = (mm: number) => Math.round((mm / 0.254) * 10);

            const existing = existingMap.get(designator);

            if (existing && typeof existing.modify === 'function') {
                // Move existing component
                await existing.modify({
                    x: toUnits(x),
                    y: toUnits(y),
                    rotation,
                    layer: side === 'bottom' ? 'B.Cu' : 'F.Cu',
                });
                placed.push(designator);
            } else if (typeof (eda as any).pcb_PrimitiveComponent?.create === 'function') {
                // Try to create by looking up from schematic
                // In practice, most PCB workflows sync from schematic first
                eda.sys_Message.showToastMessage(
                    `PCB: Component ${designator} not found in PCB — sync from schematic first`,
                    ESYS_ToastMessageType.WARNING
                );
                failed.push({ designator, error: 'Component not found in PCB — sync from schematic first' });
            } else {
                // API not available (offline/unsupported context)
                failed.push({ designator, error: 'PCB placement API not available in this context' });
            }
        } catch (err) {
            failed.push({
                designator: placement.designator,
                error: err instanceof Error ? err.message : String(err),
            });
        }
    }

    if (placed.length) {
        eda.sys_Message.showToastMessage(`PCB: Placed ${placed.length} component(s)`, ESYS_ToastMessageType.SUCCESS);
    }

    return { placed, failed };
}

/**
 * Check whether the PCB editor is currently active.
 */
export function isPcbEditorActive(): boolean {
    try {
        // @ts-ignore
        return typeof eda.pcb_PrimitiveComponent !== 'undefined';
    } catch (_) {
        return false;
    }
}

// Extend EDA global type declaration
declare global {
    interface EDA {
        placePcbComponents: typeof placePcbComponents;
        isPcbEditorActive: typeof isPcbEditorActive;
    }
}
