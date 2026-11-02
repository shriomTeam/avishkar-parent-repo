import { Suspense, type ReactNode } from "react";
import { notFound } from "next/navigation";

import { Shell } from "../components/shell";
import { FrameSkeleton } from "../components/skeletons";
import { currentRole, loadSettings } from "../lib/server";

/**
 * The page's own gate. The platform's feature check (`requireFeature`) cannot be used while this feature is not
 * "available" on the platform, so the API's answer is the gate (see lib/gate.ts). When `available` becomes true,
 * replace the body of Gate with `await requireFeature("lead_response")` from @clinic/core/web/api.
 */
async function Gate({ children }: { children: ReactNode }) {
  const loaded = await loadSettings();
  if (loaded.gate === "not_found") notFound();
  return <Shell role={await currentRole()}>{children}</Shell>;
}

export default function LeadResponseLayout({ children }: { children: ReactNode }) {
  return (
    <Suspense fallback={<FrameSkeleton />}>
      <Gate>{children}</Gate>
    </Suspense>
  );
}
