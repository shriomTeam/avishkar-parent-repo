/** Who may run an analysis and import a file. The API enforces the same rule; this only decides what to show. */
export const CAN_RUN = new Set(["owner", "office_manager"]);

export function canRunRole(role: string | null | undefined): boolean {
  return !!role && CAN_RUN.has(role);
}
