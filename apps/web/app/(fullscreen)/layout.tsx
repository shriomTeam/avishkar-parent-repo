import type { ReactNode } from "react";
import { requireAuth } from "@/lib/auth/server";
import { AuthProvider } from "@/lib/auth/provider";

export default async function FullscreenLayout({
  children,
}: {
  children: ReactNode;
}) {
  const auth = await requireAuth();
  return <AuthProvider initial={auth}>{children}</AuthProvider>;
}
