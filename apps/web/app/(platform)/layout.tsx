import Link from "next/link";
import { PlatformFrame } from "@/components/platform-frame";
import type { ReactNode } from "react";

import { getMe } from "@/lib/api";
import { requireAuth } from "@/lib/auth/server";
import { SignOut } from "@/components/auth/sign-out";
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
          <aside className="border-b border-stone-200 bg-white md:w-60 md:shrink-0 md:border-b-0 md:border-r">
            <div className="px-5 py-4">
              <Link href="/" className="text-sm font-semibold">
                Always-On Clinic
              </Link>
              {me && (
                <div
                  data-testid="clinic-name"
                  className="mt-0.5 text-xs text-stone-500"
                >
                  {me.tenant_name}
                </div>
              )}
            </div>
            {me && (
              <nav className="flex gap-1 overflow-x-auto px-3 pb-3 md:flex-col">
                <NavLink href="/">Overview</NavLink>
                <NavLink href="/import">Import data</NavLink>
                {/* Only features this tenant has, for this user's role (from /me). */}
                {me.nav.map((item) => (
                  <NavLink key={item.path} href={item.path}>
                    {item.label}
                  </NavLink>
                ))}
              </nav>
            )}
            <div className="border-t border-stone-100 px-5 py-4 text-xs">
              <p>{auth.user.display_name}</p>
              <SignOut />
            </div>
          </aside>
        }
      >
        {me ? children : <NoTenant />}
      </PlatformFrame>
    </AuthProvider>
  );
}

function NavLink({ href, children }: { href: string; children: ReactNode }) {
  return (
    <Link
      href={href}
      className="whitespace-nowrap rounded px-2 py-1.5 text-sm text-stone-700 hover:bg-stone-100"
    >
      {children}
    </Link>
  );
}

function NoTenant() {
  return <p>Unable to load this clinic. Please refresh or sign in again.</p>;
}
