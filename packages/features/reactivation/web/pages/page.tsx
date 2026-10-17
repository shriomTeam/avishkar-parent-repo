import { api } from "@clinic/core/web/api";

import { Overview, type OverviewData } from "../components/overview";

const IN_FLIGHT = new Set(["queued", "running"]);

export default async function OverviewPage() {
  const { client } = await api();
  const [runsRes, latestRes] = await Promise.all([
    client.GET("/features/reactivation/runs"),
    client.GET("/features/reactivation/runs/latest"),
  ]);
  // No completed run yet is a normal first-time state, not an error.
  if (!runsRes.data || (!latestRes.data && latestRes.response.status !== 404))
    throw new Error("Could not load the analysis");

  const runs = runsRes.data;
  const latest = latestRes.data ?? null;
  const active = runs.find((r) => IN_FLIGHT.has(r.status)) ?? null;
  const newest = runs[0];
  const typesRes = latest
    ? await client.GET("/features/reactivation/runs/{run_id}/types", {
        params: { path: { run_id: latest.id } },
      })
    : null;
  if (latest && !typesRes?.data) throw new Error("Could not load the results");

  const data: OverviewData = {
    latest,
    types: typesRes?.data ?? [],
    inFlight: active
      ? { id: active.id, status: active.status, progress_pct: active.progress_pct }
      : null,
    // Only a failure newer than the shown results matters, and only when nothing is running now.
    failedCode:
      !active && newest && newest.status === "failed" && newest.id !== latest?.id
        ? newest.error_code
        : undefined,
  };
  return <Overview data={data} />;
}
