import { ReviewsShell } from "../components/shell";
import { requireFeature } from "@clinic/core/web/api";

export default async function ReviewsLayout({ children }: { children: React.ReactNode }) {
  await requireFeature("reviews");
  return (
    <div className="flex min-h-screen items-stretch bg-canvas font-brand text-[16px] leading-normal text-ink max-app:block">
      <ReviewsShell>{children}</ReviewsShell>
    </div>
  );
}
