import { CircuitAssembly, ExplainCircuit } from "../types/circuit";
import { isEasyEda } from "./utils";
// @ts-ignore
import type _ from '@jlceda/pro-api-types';
import type { AssemblyRuntimeError } from "../types/eda";
import "../types/eda";

export const assembleCircuit = async (circuit: CircuitAssembly): Promise<AssemblyRuntimeError[]> => {
    if (isEasyEda() && typeof eda.assembleCircuit === 'function') {
        const result = await eda.assembleCircuit(circuit);
        // v2.3.7: forward runtime assembly errors so the chat UI can persist
        // them in the AssemblyErrors banner (toasts disappear too quickly).
        // Older extension builds returned `void`; fall back to the global
        // snapshot the extension writes for safety.
        if (Array.isArray(result)) return result;
        const fallback = (window as any).__copilotLastAssemblyErrors;
        return Array.isArray(fallback) ? fallback : [];
    }
    else {
        throw new Error('Fail assemble circuit')
    }
}