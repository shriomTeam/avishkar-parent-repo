import "./globals.css";

import type { Metadata } from "next";
import Link from "next/link";
import type { ReactNode } from "react";

import { getMe } from "@/lib/api";
import { setTenant } from "./tenant-actions";

export const metadata: Metadata = { title: "Always-On Clinic" };

export default async function RootLayout({ children }: { children: ReactNode }) {
  const me = await getMe();
  return (
    <html lang="en">
      <body className="min-h-screen text-stone-900 antialiased">
        <div className="flex min-h-screen flex-col md:flex-row">
          <aside className="border-b border-stone-200 bg-white md:w-60 md:shrink-0 md:border-b-0 md:border-r">
            <div className="px-5 py-4">
              <Link href="/" className="text-sm font-semibold">Always-On Clinic</Link>
              {me && <div className="mt-0.5 text-xs text-stone-500">{me.tenant_name}</div>}
            </div>
            {me && (
              <nav className="flex gap-1 overflow-x-auto px-3 pb-3 md:flex-col">
                <NavLink href="/">Overview</NavLink>
                <NavLink href="/import">Import data</NavLink>
                {/* Only features this tenant has, for this user's role (from /me). */}
                {me.nav.map((item) => (
                  <NavLink key={item.path} href={item.path}>{item.label}</NavLink>
                ))}
              </nav>
            )}
            <form action={setTenant} className="hidden border-t border-stone-100 px-5 py-4 md:block">
              <label className="text-xs text-stone-500" htmlFor="tenant">Dev: tenant id</label>
              <input
                id="tenant"
                name="tenant"
                defaultValue={me?.tenant_id ?? ""}
                placeholder="paste from pnpm db:seed"
                className="mt-1 w-full rounded border border-stone-300 px-2 py-1 text-xs"
              />
            </form>
          </aside>
          <main className="flex-1 px-4 py-6 md:px-8">
            {me ? children : <NoTenant />}
          </main>
        </div>
      </body>
    </html>
  );
}

function NavLink({ href, children }: { href: string; children: ReactNode }) {
  return (
    <Link href={href} className="whitespace-nowrap rounded px-2 py-1.5 text-sm text-stone-700 hover:bg-stone-100">
      {children}
    </Link>
  );
}

function NoTenant() {
  return (
    <div className="max-w-md">
      <h1 className="text-lg font-semibold">Pick a tenant</h1>
      <p className="mt-2 text-sm text-stone-600">
        Run <code className="rounded bg-stone-100 px-1">pnpm db:seed</code>, then paste the printed tenant id.
      </p>
      <form action={setTenant} className="mt-4 flex gap-2">
        <input name="tenant" className="flex-1 rounded border border-stone-300 px-2 py-1.5 text-sm" placeholder="tenant id" />
        <button className="rounded bg-teal-700 px-3 text-sm text-white">Use</button>
      </form>
    </div>
  );
}
