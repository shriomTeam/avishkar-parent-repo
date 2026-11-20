import { requireManagement } from "@clinic/core/web/api";
import { WhatsAppSettings } from "../../../components/whatsapp";
export const metadata = { title: "WhatsApp configuration" };
export default async function Page() {
  await requireManagement();
  return <WhatsAppSettings />;
}
