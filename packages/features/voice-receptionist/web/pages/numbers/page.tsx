import { requireManagement } from "@clinic/core/web/api";
import { Numbers } from "../../components/numbers";
export const metadata = { title: "Phone numbers" };
export default async function Page() {
  await requireManagement();
  return <Numbers />;
}
