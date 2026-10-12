import { AgentEditor } from "@/components/voice/agents";
export const metadata = { title: "Agent configuration" };
export default async function Page({
  params,
}: {
  params: Promise<{ agentId: string }>;
}) {
  const { agentId } = await params;
  return <AgentEditor id={agentId} />;
}
