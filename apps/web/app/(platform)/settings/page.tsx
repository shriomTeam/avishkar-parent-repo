import { requireAuth } from "@/lib/auth/server";
import { getMe, api } from "@/lib/api";
import { WorkspaceSettings } from "@/components/settings/workspace-settings";

export const metadata = { title: "Settings" };
export default async function Settings() {
  const auth = await requireAuth();
  const me = await getMe();
  if (!me) throw new Error("Unable to load clinic access");
  const { client } = await api();
  const { data, response } = await client.GET(
    "/api/v1/workspaces/{workspace_id}/settings",
    { params: { path: { workspace_id: me.tenant_id } } },
  );
  if (!response.ok || !data)
    throw new Error("Unable to load workspace settings. Please retry.");
  return (
    <WorkspaceSettings
      workspace={data}
      role={me.role}
      user={auth.user}
      activeProducts={me.features.filter((f) => f.enabled).length}
    />
  );
}
