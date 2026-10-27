"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@clinic/core/web/auth/provider";

import { browserClient } from "../lib/client";
import { canRunRole } from "../lib/roles";
import { settingsInUse } from "../lib/settings";
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
  const allowed = canRunRole(role);
  // Read after the page is up, so the importer never waits for it. Nothing is shown until it arrives.
  const [settingsVersion, setSettingsVersion] = useState<number | null>(null);
  useEffect(() => {
    if (!allowed) return;
    let live = true;
    browserClient(auth.csrf_token, auth.workspace?.id)
      .GET("/features/reactivation/schedule")
      .then(({ data }) => live && data && setSettingsVersion(data.settings_version))
      .catch(() => {});
    return () => {
      live = false;
    };
  }, [allowed, auth.csrf_token, auth.workspace?.id]);
  if (!allowed) return <ImportRefused />;
  return (
    <div className="dp-stack" data-testid="import-page">
      <PageHead title="Import data" description="Import a CSV export from your booking or billing system." />
      {settingsVersion !== null && (
        <p className="dp-small" data-testid="import-settings">
          The file is analysed with {settingsInUse(settingsVersion)}.{" "}
          <Link href={`${ROOT}/settings`}>Change settings</Link>
        </p>
      )}
      <CsvImportPanel onDone={() => router.push(ROOT)} />
      <CsvHelp />
    </div>
  );
}
