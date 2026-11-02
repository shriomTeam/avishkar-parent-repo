import { cache } from "react";
import { api } from "@clinic/core/web/api";
import { getAuth } from "@clinic/core/web/auth/server";

import { classifyGate, type Gate } from "./gate";
import type { Config } from "./settings";

export type SavedSettings = {
  version: number;
  config: Config;
  defaults: Config;
  timezone: string;
  updatedAt: string | null;
};
export type Loaded = { gate: "ok"; data: SavedSettings } | { gate: Exclude<Gate, "ok"> };

/**
 * One read of the settings per page render (the layout and the page share it). It is also the feature gate: see gate.ts.
 * A network failure is an error the person can retry, never a 404.
 */
export const loadSettings = cache(async (): Promise<Loaded> => {
  try {
    const { client } = await api();
    const { data, error, response } = await client.GET("/features/lead_response/settings");
    const gate = classifyGate(response.status, (error as { detail?: unknown } | undefined)?.detail);
    if (gate !== "ok") return { gate };
    if (!data) return { gate: "error" };
    return {
      gate: "ok",
      data: {
        version: data.version,
        config: data.config as Config,
        defaults: data.defaults as Config,
        timezone: data.timezone,
        updatedAt: data.updated_at ?? null,
      },
    };
  } catch {
    return { gate: "error" };
  }
});

/** The signed-in person's role in the current clinic, for the page's own wording (the API enforces it either way). */
export const currentRole = cache(async (): Promise<string | null> => {
  try {
    const auth = await getAuth();
    return auth?.memberships.find((m) => m.workspace_id === auth.workspace?.id)?.role ?? null;
  } catch {
    return null;
  }
});
