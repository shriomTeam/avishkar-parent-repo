import { requireManagement } from "@clinic/core/web/api";
import { Tools } from "../../components/tools";
export const metadata = { title: "Tools" };
export default async function Page() {
  await requireManagement();
  return <Tools />;
}
