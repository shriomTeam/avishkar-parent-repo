import "../styles/reactivation.css";
import type { ReactNode } from "react";
import { requireFeature } from "@clinic/core/web/api";

import { CsvResultProvider } from "../components/csv-provider";
import { Shell } from "../components/shell";

export default async function ReactivationLayout({
  children,
}: {
  children: ReactNode;
}) {
  const me = await requireFeature("reactivation");
  return (
    <div className="dp-scope">
      <CsvResultProvider>
        <Shell clinicName={me.tenant_name || "Your clinic"}>{children}</Shell>
      </CsvResultProvider>
    </div>
  );
}
