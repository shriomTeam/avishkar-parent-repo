import type { DemoCommand, DemoState } from "@/lib/voice/types";
// Replace this adapter with server-backed operations after the API contract is agreed.
export interface DashboardService {
  load(): Promise<DemoState>;
  execute(state: DemoState, command: DemoCommand): Promise<DemoState>;
}
