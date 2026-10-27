import { requireManagement } from "@clinic/core/web/api";
import { AgentList } from "../../components/agents";
export const metadata = { title: "Voice agents" };
export default async function Page() {
  await requireManagement();
  return <AgentList />;
}
