import "../styles/reviews.css";
import { ReviewsShell } from "../components/shell";
import { requireFeature } from "@clinic/core/web/api";

export default async function ReviewsLayout({ children }: { children: React.ReactNode }) {
  await requireFeature("reviews");
  return (
    <div className="reviews-scope">
      <ReviewsShell>{children}</ReviewsShell>
    </div>
  );
}
