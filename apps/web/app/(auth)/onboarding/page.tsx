import { Onboarding } from "@/components/auth/onboarding";
import { AuthProvider } from "@/lib/auth/provider";
import { requireAuth } from "@/lib/auth/server";
export const metadata = { title: "Workspace setup" };
export default async function Page() {
  const auth = await requireAuth(true);
  return (
    <AuthProvider initial={auth}>
      <Onboarding />
    </AuthProvider>
  );
}
