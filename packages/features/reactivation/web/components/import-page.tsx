"use client";
import { useRouter } from "next/navigation";
import { useAuth } from "@clinic/core/web/auth/provider";

import { canRunRole } from "../lib/roles";
import { CsvHelp } from "./csv-help";
import { CsvImportPanel } from "./csv-import";
import { Card, EmptyState, PageHead } from "./kit";
import { ROOT } from "./shell-nav";

export const REFUSED = "Your role can't import files. Ask the clinic owner or office manager.";

/** Shown instead of the importer to a role that cannot import. The API refuses the calls as well. */
export function ImportRefused() {
  return (
    <div className="dp-stack" data-testid="import-refused">
      <PageHead title="Import data" />
      <Card>
        <EmptyState title="You can't import files">{REFUSED}</EmptyState>
      </Card>
    </div>
  );
}

/** The importer on its own page. A finished import goes to the Overview, which then shows the file results. */
export function ImportPage() {
  const { auth } = useAuth();
  const router = useRouter();
  const role = auth.memberships.find((m) => m.workspace_id === auth.workspace?.id)?.role;
  if (!canRunRole(role)) return <ImportRefused />;
  return (
    <div className="dp-stack" data-testid="import-page">
      <PageHead title="Import data" description="Import a CSV export from your booking or billing system." />
      <CsvImportPanel onDone={() => router.push(ROOT)} />
      <CsvHelp />
    </div>
  );
}
