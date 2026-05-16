import { CircuitAssembly, ExplainCircuit } from "./circuit";
import { SimulateResult } from "./spice";
// @ts-ignore
import type _ from '@jlceda/pro-api-types';

export interface AssemblyRuntimeError {
    component?: string;
    message: string;
    severity: 'info' | 'warning' | 'error';
}

declare global {
    interface EDA {
        assembleCircuit?: (circuit: CircuitAssembly) => Promise<AssemblyRuntimeError[] | void>,
        getSchematic?: (primitiveIds?: string[]) => Promise<ExplainCircuit>,
        checkpointer?: {
            restore: (id?: string) => Promise<boolean>;
            save: (minor: boolean) => Promise<string | null>;
            hasCheckpoint: () => boolean;
        }
        simulationResult?: SimulateResult
    }
}