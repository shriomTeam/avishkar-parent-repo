"use client";
export default function ErrorPage({ reset }: { reset: () => void }) {
  return (
    <main className="standalone">
      <h1>Unable to load your workspace</h1>
      <p>The service is temporarily unavailable. Please retry.</p>
      <button className="primary" onClick={reset}>
        Try again
      </button>
    </main>
  );
}
