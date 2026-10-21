import { Card, EmptyState, PageHead } from "../../components/kit";

export default function RunsPage() {
  return (
    <>
      <PageHead title="Runs" description="Every analysis your clinic has run." />
      <Card>
        <EmptyState title="Run history is coming soon">
          You&apos;ll be able to see each analysis, compare it with an earlier
          one, and open its results here.
        </EmptyState>
      </Card>
    </>
  );
}
