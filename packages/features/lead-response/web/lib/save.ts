/** What the page says after the server accepts a save. Pure, so the wording can be tested. */
import { changedSettings, savedMessage, UNCHANGED_MESSAGE } from "./messages";
import type { Config } from "./settings";

export type Outcome = { kind: "saved" | "unchanged"; text: string; changed: string[] };

/**
 * The server returns the same version when nothing differed from what it already held (no new version, no audit
 * entry); a higher version means a new one was written. `changed` lists setting names, never values.
 */
export function saveOutcome(before: { version: number; config: Config }, after: { version: number; config: Config }): Outcome {
  if (after.version === before.version) return { kind: "unchanged", text: UNCHANGED_MESSAGE, changed: [] };
  return { kind: "saved", text: savedMessage(after.version), changed: changedSettings(before.config, after.config) };
}
