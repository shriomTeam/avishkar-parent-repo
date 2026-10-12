import { Badge, Card, PageHeader } from "@clinic/ui";
import Link from "next/link";

import { requireAuth } from "@/lib/auth/server";
import { getMe } from "@/lib/api";

export default async function Overview() {
  await requireAuth();
  const me = await getMe();
  if (!me) throw new Error("Unable to load clinic access");
  const navByFeature = new Map(me.nav.map((n) => [n.feature, n.path]));
  return (
    <>
      <PageHeader
        title={me.tenant_name}
        description={`${me.clinic_type} · ${me.tenant_status === "trial" ? "trial (lead magnet)" : me.tenant_status}`}
      />
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {me.features.map((f) => (
          <Card
            key={f.key}
            title={f.name}
            action={
              f.enabled ? (
                <Badge tone="good">Active</Badge>
              ) : (
                <Badge tone="locked">Not in plan</Badge>
              )
            }
          >
            <p className="text-sm text-stone-600">{f.description}</p>
            {f.enabled && navByFeature.get(f.key) && (
              <Link
                href={navByFeature.get(f.key)!}
                className="mt-3 inline-block text-sm font-medium text-teal-700"
              >
                Open →
              </Link>
            )}
            {f.phi_sensitive && (
              <p className="mt-3 text-xs text-stone-500">
                Handles PHI: requires BAA and patient consent.
              </p>
            )}
          </Card>
        ))}
      </div>
    </>
  );
}
