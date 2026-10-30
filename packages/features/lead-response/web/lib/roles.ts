/** Who may change the settings. The server decides (owner and office manager); this only shapes what the page shows. */
export const EDITOR_ROLES = ["owner", "office_manager"] as const;

export function canEditSettings(role: string | null | undefined): boolean {
  return !!role && (EDITOR_ROLES as readonly string[]).includes(role);
}
