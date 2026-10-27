import { Muted } from "@clinic/ui";

export default function Loading() {
  return (
    <div className="mx-auto max-w-[700px] px-[30px] py-[70px]">
      <Muted role="status">Loading your workspace…</Muted>
    </div>
  );
}
