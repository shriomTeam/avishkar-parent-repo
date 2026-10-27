import { getAuth } from "@/lib/auth/server";
import { InvitationAcceptance } from "@/components/auth/invitation-acceptance";
export const metadata = {
  title: "Workspace invitation",
  referrer: "no-referrer",
};
export default async function Page() {
  return <InvitationAcceptance initial={await getAuth()} />;
}
