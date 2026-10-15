import { createSeed } from "../demo/seed";
import type { DashboardService } from "./dashboard";
import type { DemoCommand, DemoState } from "../types";
function upsert<T extends { id: string }>(items: T[], item: T): T[] {
  return items.some((x) => x.id === item.id)
    ? items.map((x) => (x.id === item.id ? item : x))
    : [...items, item];
}
export function applyCommand(
  state: DemoState,
  command: DemoCommand,
): DemoState {
  if (command.type === "reset") return createSeed();
  let next = state;
  let event = "";
  switch (command.type) {
    case "save-agent":
      next = { ...state, agents: upsert(state.agents, command.agent) };
      event = command.event;
      break;
    case "save-number":
      next = { ...state, numbers: upsert(state.numbers, command.number) };
      event = "Phone routing updated";
      break;
    case "save-tool":
      next = { ...state, tools: upsert(state.tools, command.tool) };
      event = "Tool configuration saved";
      break;
    case "save-variable":
      next = { ...state, variables: upsert(state.variables, command.variable) };
      event = "Variable saved";
      break;
    case "save-workspace":
      next = {
        ...state,
        workspace: command.workspace,
        variables: state.variables.map((v) =>
          v.name === "company_name"
            ? { ...v, value: command.workspace.name }
            : v,
        ),
      };
      event = "Workspace settings updated";
      break;
    case "add-call":
      next = { ...state, calls: [command.call, ...state.calls] };
      event = "Simulated call completed";
      break;
  }
  return {
    ...next,
    audit: [
      {
        id: crypto.randomUUID(),
        event,
        actor: "Jamie Davis",
        at: new Date().toISOString(),
      },
      ...state.audit,
    ],
  };
}
export const mockDashboardService: DashboardService = {
  async load() {
    return createSeed();
  },
  async execute(state, command) {
    return applyCommand(state, command);
  },
};
