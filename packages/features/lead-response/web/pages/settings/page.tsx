import { SettingsForm } from "../../components/settings-form";
import { LoadError, RoleView } from "../../components/views";
import { canEditSettings } from "../../lib/roles";
import { currentRole, loadSettings } from "../../lib/server";

export default async function SettingsPage() {
  const loaded = await loadSettings();
  if (loaded.gate === "role") return <RoleView />;
  if (loaded.gate !== "ok") return <LoadError />;
  // The API lets only these roles save; a role it lets read but not edit would only see a form that always fails.
  if (!canEditSettings(await currentRole())) return <RoleView />;
  return <SettingsForm initial={loaded.data} />;
}
