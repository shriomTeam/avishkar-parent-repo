import type { ReactNode } from "react";

/** A short message page inside the workspace shell (not found, unable to load). */
export function StandalonePage({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <div className="mx-auto max-w-[700px] px-[30px] py-[70px]">
      <h1 className="mb-[5px] text-[30px] font-[650] tracking-[-1px] max-app:text-[26px]">
        {title}
      </h1>
      {children}
    </div>
  );
}
