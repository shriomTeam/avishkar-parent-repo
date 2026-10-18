import "../styles/reactivation.css";
import type { ReactNode } from "react";
import { requireFeature } from "@clinic/core/web/api";

import { CsvResultProvider } from "../components/csv-provider";
import { SectionTabs } from "../components/section-tabs";

export default async function ReactivationLayout({
  children,
}: {
  children: ReactNode;
}) {
  await requireFeature("reactivation");
  return (
    <div className="dp-scope">
      <CsvResultProvider>
        <p className="dp-eyebrow">Dormant patients</p>
        <SectionTabs />
        {children}
      </CsvResultProvider>
    </div>
  );
}
