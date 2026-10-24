"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Avatar, buttonStyles, StatusBadge } from "@clinic/ui";
import { SignOut } from "@clinic/core/web/auth/sign-out";
import { useAuth } from "@clinic/core/web/auth/provider";
import { initials } from "@clinic/core/web/auth/types";

function Icon({ d }: { d: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      width="19"
      height="19"
      aria-hidden="true"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d={d} />
    </svg>
  );
}

const navigation = [
  { href: "/reviews", name: "Overview", d: "M4 10.5 12 4l8 6.5V20a1 1 0 0 1-1 1h-5v-6H10v6H5a1 1 0 0 1-1-1z" },
  {
    href: "/reviews#google",
    name: "Google profile",
    d: "m12 3 2.4 5.7L20.5 9.5l-4.4 3.8 1.3 6.2L12 16.8 6.6 19.5l1.3-6.2L3.5 9.5l6.1-.8z",
  },
  { href: "/reviews#campaigns", name: "Campaigns", d: "M4 10v4l12 6V4zM16 9.5v5M19 8a6 6 0 0 1 0 8" },
  { href: "/reviews#follow-ups", name: "Follow-ups", d: "M4 6h16v10H7l-3 3z" },
];

export function ReviewsShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { auth } = useAuth();
  const clinic = auth.workspace?.name || "Reviews workspace";
  const role =
    auth.memberships.find((member) => member.workspace.id === auth.workspace?.id)?.role ||
    auth.memberships[0]?.role ||
    "Member";

  return (
    <>
      <a className="fixed -top-[100px] left-4 z-[200] bg-ink p-3 text-white focus:top-3" href="#main-content">
        Skip to content
      </a>
      <aside className="sticky top-0 flex h-screen w-[245px] shrink-0 flex-col overflow-auto border-r border-line bg-white px-5 py-[30px] max-[1100px]:w-[205px] max-[1100px]:px-3 max-[1100px]:py-[25px] max-app:relative max-app:h-auto max-app:w-full max-app:p-4">
        <Link
          className="focus-ring flex items-center gap-[9px] px-[7px] text-[29px] font-[750] tracking-[-1.2px] max-app:text-[24px]"
          href="/reviews"
        >
          <img className="size-[34px] shrink-0 object-contain" src="/brand/avishkar-logo.png" alt="" width={34} height={34} />
          avishkar
        </Link>
        <div className="my-7 flex gap-3 rounded-xl border border-line px-2.5 py-[17px] text-[14px] max-app:hidden">
          <Avatar>{clinic[0] || "R"}</Avatar>
          <div>
            <strong className="block max-w-[140px] [overflow-wrap:anywhere]">{clinic}</strong>
            <small className="block text-[12px] text-muted">Reviews workspace</small>
          </div>
        </div>
        <Link className="focus-ring -mt-2.5 mx-3 mb-[18px] block text-[12px] text-muted max-app:mt-3" href="/">
          ← All clinic products
        </Link>
        <div className="mx-3 mb-2.5 text-[12px] tracking-[1.2px] text-[#96929f] max-app:hidden">WORKSPACE</div>
        <nav aria-label="Workspace navigation" className="max-app:mt-3 max-app:flex max-app:gap-1 max-app:overflow-auto">
          {navigation.map(({ href, name, d }) => {
            const active = href === "/reviews" && pathname === "/reviews";
            return (
              <Link
                key={href}
                href={href}
                aria-current={active ? "page" : undefined}
                className={`focus-ring my-[3px] flex items-center gap-[13px] rounded-[9px] p-3 text-[14px] max-app:whitespace-nowrap max-app:p-[9px] ${active ? "bg-brand-soft font-semibold text-brand-ink" : "text-[#625d6b]"}`}
              >
                <Icon d={d} />
                {name}
              </Link>
            );
          })}
        </nav>
        <div className="mt-auto max-app:hidden">
          <div className="flex gap-3 px-[5px] pt-5 text-[14px]">
            <Avatar tone="dark">{initials(auth.user.display_name)}</Avatar>
            <div>
              <strong>{auth.user.display_name}</strong>
              <small className="block text-[12px] text-muted">{role}</small>
            </div>
          </div>
          <SignOut className={buttonStyles("outline", { className: "mt-3 w-full" })} />
        </div>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col max-app:block">
        <header className="flex h-[79px] items-center justify-between border-b border-line bg-white px-[38px] text-[14px] text-muted max-[1100px]:px-6 max-app:h-auto max-app:min-h-[60px] max-app:px-[18px] max-app:py-3">
          <span className="inline-flex items-center gap-1.5">
            Workspace{" "}
            <svg viewBox="0 0 24 24" width="13" height="13" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
              <path d="m9 6 6 6-6 6" />
            </svg>{" "}
            <strong className="font-medium text-ink">Reviews</strong>
          </span>
          <StatusBadge>4–5 stars go to Google</StatusBadge>
        </header>
        <main id="main-content" className="mx-auto min-h-[calc(100vh-138px)] w-full max-w-[1440px] px-[38px] pb-[45px] pt-[34px] max-[1100px]:px-6 max-app:px-[18px] max-app:py-[25px]">
          {children}
        </main>
        <footer className="border-t border-line px-[38px] py-[18px] text-[12px] text-muted max-[1100px]:px-6 max-app:px-[18px]">
          Avishkar Reviews
        </footer>
      </div>
    </>
  );
}
