import { requireManagement } from "@clinic/core/web/api";
import { AgentEditor } from "../../../components/agents";
export const metadata = { title: "Agent configuration" };
export default async function Page({
  params,
}: {
  params: Promise<{ agentId: string }>;
}) {
  await requireManagement();
  const { agentId } = await params;
  return <AgentEditor id={agentId} />;
}
