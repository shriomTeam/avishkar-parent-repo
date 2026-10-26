import {
  buttonStyles,
  PageHeading,
  ProductCard,
  ProductGrid,
} from "@clinic/ui";
import { ArrowUpRight, ShieldCheck, Upload } from "lucide-react";
import Link from "next/link";
import { requireAuth } from "@/lib/auth/server";
import { getMe } from "@/lib/api";
import { featurePresentation } from "@/lib/feature-presentation";

export default async function Overview() {
  const auth = await requireAuth();
  const me = await getMe();
  if (!me) throw new Error("Unable to load clinic access");
  const navByFeature = new Map(me.nav.map((n) => [n.feature, n]));
  const visible = me.features.filter((f) => f.accessible);
  const active = visible.filter((f) => f.enabled);
  const available = visible.filter((f) => !f.enabled);
  const upcomingCount = available.filter((f) => !f.available).length;
  const inactiveCount = available.length - upcomingCount;
  const firstName = auth.user.display_name.trim().split(/\s+/)[0];
  const card = (feature: (typeof me.features)[number]) => {
    const presentation = featurePresentation(feature);
    const Icon = presentation.icon;
    const nav = navByFeature.get(feature.key);
    return (
      <ProductCard
        key={feature.key}
        title={presentation.title}
        description={presentation.description}
        icon={<Icon size={22} strokeWidth={1.7} />}
        active={feature.enabled}
        available={feature.available}
        action={
          feature.enabled &&
          (nav ? (
            <Link
              href={nav.path}
              className="focus-ring inline-flex items-center gap-2 rounded hover:underline"
            >
              Open {nav.label}
              <ArrowUpRight size={16} aria-hidden="true" />
            </Link>
          ) : (
            <span className="text-muted">
              Contact your workspace administrator for access.
            </span>
          ))
        }
      />
    );
  };
  return (
    <div className="mx-auto max-w-[1500px]">
      <PageHeading
        title={firstName ? `Welcome back, ${firstName}.` : "Welcome back."}
        description="Your clinic’s tools, connected in one place."
        actions={
          ["owner", "office_manager"].includes(me.role) && (
            <Link href="/import" className={buttonStyles("brand")}>
              <Upload size={16} aria-hidden="true" />
              Import data
            </Link>
          )
        }
      />
      <div className="mb-9 flex flex-wrap items-center gap-3 text-[12px] text-muted">
        <span className="inline-flex items-center gap-2">
          <span className="size-1.5 rounded-full bg-green-600" />
          {active.length} active {active.length === 1 ? "product" : "products"}
        </span>
        <span aria-hidden="true">·</span>
        <span>
          {upcomingCount} upcoming products
          {inactiveCount > 0 && ` · ${inactiveCount} inactive products`}
        </span>
      </div>
      <section aria-labelledby="active-products">
        <div className="mb-5">
          <h2
            id="active-products"
            className="text-[19px] font-semibold tracking-[-0.5px]"
          >
            Your active products
          </h2>
          <p className="mt-1 text-[13px] text-muted">
            Pick up where you left off.
          </p>
        </div>
        {active.length ? (
          <ProductGrid>{active.map(card)}</ProductGrid>
        ) : (
          <p className="text-sm text-muted">
            No products are active in this workspace yet.
          </p>
        )}
      </section>
      {available.length > 0 && (
        <section aria-labelledby="available-products" className="mt-9">
          <div className="mb-5">
            <h2
              id="available-products"
              className="text-[19px] font-semibold tracking-[-0.5px]"
            >
              {inactiveCount > 0 ? "More for your clinic" : "Upcoming products"}
            </h2>
            <p className="mt-1 text-[13px] text-muted">
              Explore what’s coming next for your clinic.
            </p>
          </div>
          <ProductGrid>{available.map(card)}</ProductGrid>
        </section>
      )}
      <footer className="mt-9 flex flex-wrap items-center justify-between gap-4 border-t border-line pt-5 text-[11px] text-muted">
        <p className="flex items-center gap-2">
          <ShieldCheck size={15} className="shrink-0" aria-hidden="true" />
          Sensitive workflows require a signed BAA and patient consent.
        </p>
        <span>Avishkar · Your always-on clinic</span>
      </footer>
    </div>
  );
}
