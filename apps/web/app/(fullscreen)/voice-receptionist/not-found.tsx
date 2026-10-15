import Link from "next/link";
export default function NotFound() {
  return (
    <main className="standalone">
      <h1>Page not found</h1>
      <p>This page is not part of the workspace.</p>
      <Link className="button primary" href="/voice-receptionist">
        Back to dashboard
      </Link>
    </main>
  );
}
