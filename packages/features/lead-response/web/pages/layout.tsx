import { Suspense, type ReactNode } from "react";
import { notFound } from "next/navigation";

import { Shell } from "../components/shell";
import { FrameSkeleton } from "../components/skeletons";
import { currentRole, loadSettings } from "../lib/server";

/**
 * The page's own gate. The API's answer is the gate (see lib/gate.ts), not the platform's `requireFeature`, on
 * purpose: `requireFeature` answers 404 to a role the platform does not grant the feature, while this page shows such
 * a role an explanation (the role view). Revisit when the staff task API opens the feature to more roles.
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
