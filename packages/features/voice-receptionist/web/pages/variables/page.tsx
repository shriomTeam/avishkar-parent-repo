import { requireManagement } from "@clinic/core/web/api";
import { Variables } from "../../components/variables";
export const metadata = { title: "Variables" };
export default async function Page() {
  await requireManagement();
  return <Variables />;
}
