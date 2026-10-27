import { redirect } from "next/navigation";
import { Panel, PageHeading } from "@clinic/ui";
import { getAuth } from "@/lib/auth/server";
import { AuthProvider } from "@/lib/auth/provider";
import { WorkspaceChoices } from "@/components/auth/workspace-switcher";
export default async function Page() {
  const auth = await getAuth();
  if (!auth) redirect("/login");
  if (!auth.memberships.length) redirect("/onboarding");
  return (
    <AuthProvider initial={auth}>
      <main className="mx-auto max-w-xl px-5 py-16">
        <PageHeading
          title="Choose your workspace"
          description="Select a workspace you currently have access to."
        />
        <Panel>
          <WorkspaceChoices />
        </Panel>
      </main>
    </AuthProvider>
  );
}
