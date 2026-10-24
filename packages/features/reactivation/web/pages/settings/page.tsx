import { api } from "@clinic/core/web/api";

import { Card, EmptyState, PageHead } from "../../components/kit";
import type { Config } from "../../lib/settings";
import { SettingsForm } from "../../components/settings-form";

export default async function SettingsPage() {
  const { client } = await api();
  const { data, response } = await client.GET("/features/reactivation/settings");
  if (response.status === 403)
    return (
      <>
        <PageHead title="Settings" description="How patients are judged dormant and what they could be worth." />
        <Card>
          <EmptyState title="Only the owner or office manager can change settings" testId="settings-forbidden">
            Ask them if you need a figure changed. Your analyses keep using the saved settings.
          </EmptyState>
        </Card>
      </>
    );
  if (!data) throw new Error("Could not load the settings");
  return <SettingsForm initial={{ version: data.version, config: data.config as Config, defaults: data.defaults as Config }} />;
}
