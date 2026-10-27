import { requireManagement } from "@clinic/core/web/api";
import { KnowledgeBase } from "../../components/knowledge";
export const metadata = { title: "Knowledge base" };
export default async function Page() {
  await requireManagement();
  return <KnowledgeBase />;
}
