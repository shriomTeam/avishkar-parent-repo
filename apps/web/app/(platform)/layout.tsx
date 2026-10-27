import type { ReactNode } from "react";
import { PlatformFrame } from "@/components/platform-frame";
import {
  PlatformHeader,
  PlatformNavigation,
} from "@/components/platform-navigation";
import { getMe } from "@/lib/api";
import { requireAuth } from "@/lib/auth/server";
import { AuthProvider } from "@/lib/auth/provider";

export default async function RootLayout({
  children,
}: {
  children: ReactNode;
}) {
  const auth = await requireAuth();
  const me = await getMe();
  return (
    <AuthProvider initial={auth}>
      <PlatformFrame
        sidebar={
          me && (
            <PlatformNavigation
              name={me.tenant_name}
              clinicType={me.clinic_type}
              status={me.tenant_status}
              userName={auth.user.display_name}
              role={me.role}
              nav={me.nav}
            />
          )
        }
        header={
          me && (
            <PlatformHeader userName={auth.user.display_name} nav={me.nav} />
          )
        }
      >
        {me ? (
          children
        ) : (
          <p>Unable to load this clinic. Please refresh or sign in again.</p>
        )}
      </PlatformFrame>
    </AuthProvider>
  );
}
