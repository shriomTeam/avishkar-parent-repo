import {
  Badge,
  Button,
  Card,
  PageHeader,
  Stat,
  Table,
  formatCents,
} from "@clinic/ui";

import { api, requireFeature } from "@/lib/api";
import { createCampaign, launchCampaign } from "./actions";

export default async function ReactivationPage() {
  await requireFeature("reactivation");
  const { client } = await api();
  const [{ data: preview }, { data: campaigns }] = await Promise.all([
    client.GET("/features/reactivation/preview"),
    client.GET("/features/reactivation/campaigns"),
  ]);
  if (!preview || !campaigns)
    throw new Error("Failed to load reactivation data");

  return (
    <>
      <PageHeader
        title="Dormant Revenue Finder"
        description={`Patients with no completed visit in the last ${preview.lapsed_days} days and nothing booked.`}
        action={
          <form action={createCampaign}>
            <Button type="submit" disabled={preview.dormant_patients === 0}>
              Create campaign
            </Button>
          </form>
        }
      />
      <div className="mb-6 grid gap-4 sm:grid-cols-3">
        <Stat label="Dormant patients" value={preview.dormant_patients} />
        <Stat
          label="Their lifetime spend"
          value={formatCents(preview.dormant_lifetime_value_cents)}
          hint="Revenue these patients brought in before going quiet"
        />
        <Stat
          label="Booked back"
          value={campaigns.reduce((n, c) => n + c.stats.booked, 0)}
          hint="Across all campaigns"
        />
      </div>

      <Card title="Campaigns" className="mb-6">
        {campaigns.length === 0 ? (
          <p className="text-sm text-stone-600">No campaigns yet.</p>
        ) : (
          <Table
            columns={[
              "Name",
              "Status",
              "Targets",
              "Booked",
              "Booked revenue",
              "",
            ]}
            rows={campaigns.map((c) => [
              c.name,
              <Badge key="s" tone={c.status === "running" ? "good" : "neutral"}>
                {c.status}
              </Badge>,
              String(c.stats.targets),
              String(c.stats.booked),
              formatCents(c.stats.booked_revenue_cents),
              c.status === "draft" ? (
                <form key="a" action={launchCampaign.bind(null, c.id)}>
                  <Button type="submit" variant="secondary">
                    Launch
                  </Button>
                </form>
              ) : null,
            ])}
          />
        )}
      </Card>

      <Card title="Highest-value dormant patients">
        <Table
          columns={[
            "Patient",
            "Last visit",
            "Days lapsed",
            "Visits",
            "Lifetime spend",
          ]}
          rows={preview.top.map((p) => [
            `${p.first_name ?? ""} ${p.last_name ?? ""}`.trim() || "—",
            new Date(p.last_visit_at).toLocaleDateString(),
            String(p.days_lapsed),
            String(p.visits),
            formatCents(p.lifetime_value_cents),
          ])}
        />
      </Card>
    </>
  );
}
