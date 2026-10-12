import { createContext, useContext } from 'react';

export type DemoStatus = { enabled: boolean; limit: number; used: number; remaining: number; report_center_ready: boolean };
export const DemoContext = createContext<DemoStatus | null>(null);
export function useDemoMode() { return useContext(DemoContext); }
