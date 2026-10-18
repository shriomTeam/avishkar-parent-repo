"use client";
import { Button, Card } from "@clinic/ui";

import { EmptyState } from "../components/kit";

export default function ErrorPage({ reset }: { reset: () => void }) {
  return (
    <Card>
      <EmptyState
        title="We couldn't load your results"
        action={<Button onClick={reset}>Try again</Button>}
      >
        Something went wrong while loading this page. Your data is safe. Please
        try again in a moment.
      </EmptyState>
    </Card>
  );
}
