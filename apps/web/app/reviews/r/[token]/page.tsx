import { FeedbackPage } from "@clinic/feature-reviews/web/feedback";

export const metadata = { title: "Share your experience" };

export default async function PublicReviewPage({ params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  return <FeedbackPage token={token} />;
}
