import { Card, PageHeader, Stat, formatCents } from "@clinic/ui";

import { api, requireFeature } from "@/lib/api";

export default async function BlueprintsPage() {
  await requireFeature("blueprints");
  const { client } = await api();
  const { data: report } = await client.GET("/features/blueprints/report");
  if (!report) throw new Error("Failed to load report");

  return (
    <>
      <PageHeader
        title="Patient Blueprint Report"
        description="The clinic's top buying profiles, from its own records. Use them to target marketing and cross-sell."
      />
      <div className="mb-6 grid gap-4 sm:grid-cols-2">
        <Stat label="Paying patients analysed" value={report.patients_analyzed} />
        <Stat label="Revenue analysed" value={formatCents(report.total_revenue_cents)} />
      </div>
      <div className="grid gap-4 lg:grid-cols-3">
        {report.profiles.map((p, i) => (
          <Card key={p.label} title={`#${i + 1} ${p.label}`}>
            <dl className="grid grid-cols-2 gap-y-2 text-sm">
              <dt className="text-stone-500">Share of revenue</dt>
              <dd className="text-right font-medium tabular-nums">{Math.round(p.share_of_revenue * 100)}%</dd>
              <dt className="text-stone-500">Patients</dt>
              <dd className="text-right tabular-nums">{p.patients}</dd>
              <dt className="text-stone-500">Avg spend / patient</dt>
              <dd className="text-right tabular-nums">{formatCents(p.avg_revenue_per_patient_cents)}</dd>
              <dt className="text-stone-500">Avg purchases</dt>
              <dd className="text-right tabular-nums">{p.avg_purchases}</dd>
            </dl>
          </Card>
        ))}
      </div>
    </>
  );
}
