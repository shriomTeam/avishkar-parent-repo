import "../styles/reactivation.css";
import type { ReactNode } from "react";
import { api, requireFeature } from "@clinic/core/web/api";

import { CsvResultProvider } from "../components/csv-provider";
import { Shell } from "../components/shell";
import type { Saved } from "../components/shell-status";

/** Whether the clinic has a saved analysis: a completed run exists (404 is the normal first-time state). */
async function savedState(): Promise<Saved> {
  try {
    const { client } = await api();
    const { response } = await client.GET("/features/reactivation/runs/latest");
    if (response.ok) return "saved";
    return response.status === 404 ? "none" : "unknown";
  } catch {
    return "unknown";
  }
}

export default async function ReactivationLayout({
  children,
}: {
  children: ReactNode;
}) {
  const me = await requireFeature("reactivation");
  const saved = await savedState();
  return (
    <div className="dp-scope">
      <CsvResultProvider>
        <Shell clinicName={me.tenant_name} role={me.role} saved={saved}>
          {children}
        </Shell>
      </CsvResultProvider>
    </div>
  );
}
