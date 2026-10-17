"use client";

import { useEffect, useState, type FormEvent, type ReactNode } from "react";

type FeedbackState = {
  practice_name: string;
  rating: number | null;
  comment: string | null;
  submitted: boolean;
  next_step: "form" | "google_review" | "thanks";
  google_review_url: string | null;
};

export function FeedbackPage({ token }: { token: string }) {
  const [state, setState] = useState<FeedbackState | null>(null);
  const [rating, setRating] = useState(0);
  const [comment, setComment] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetch(`/api/platform/public/reviews/${encodeURIComponent(token)}`)
      .then(async (response) => {
        if (!response.ok) throw new Error("This review link is not available.");
        return response.json() as Promise<FeedbackState>;
      })
      .then((data) => {
        if (!cancelled) setState(data);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    const response = await fetch(`/api/platform/public/reviews/${encodeURIComponent(token)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rating, comment: comment.trim() || null }),
    });
    setBusy(false);
    if (!response.ok) {
      setError("We couldn't save that rating. Please try again.");
      return;
    }
    setState(await response.json());
  }

  async function openGoogle() {
    await fetch(`/api/platform/public/reviews/${encodeURIComponent(token)}/google-click`, { method: "POST" });
  }

  if (error && !state) {
    return <Modal title="Review">{error}</Modal>;
  }
  if (!state) {
    return <Modal title="Review">Loading…</Modal>;
  }
  if (!state.submitted) {
    return (
      <Modal title={`How was your visit to ${state.practice_name}?`}>
        <form onSubmit={submit} className="grid gap-4">
          <div className="flex gap-2" role="radiogroup" aria-label="Star rating">
            {[1, 2, 3, 4, 5].map((value) => (
              <button
                key={value}
                type="button"
                role="radio"
                aria-checked={rating === value}
                onClick={() => setRating(value)}
                className={`h-11 w-11 rounded-md border text-lg ${
                  rating >= value ? "border-teal-700 bg-teal-700 text-white" : "border-stone-300 bg-white text-stone-700"
                }`}
              >
                {value}
              </button>
            ))}
          </div>
          <label className="text-sm text-stone-700">
            Comment (optional)
            <textarea
              value={comment}
              onChange={(event) => setComment(event.target.value)}
              rows={4}
              className="mt-1 w-full rounded-md border border-stone-300 px-3 py-2"
            />
          </label>
          {error && <p className="text-sm text-red-700">{error}</p>}
          <button
            type="submit"
            disabled={rating < 1 || busy}
            className="rounded-md bg-teal-700 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
          >
            Submit feedback
          </button>
        </form>
      </Modal>
    );
  }
  if (state.next_step === "google_review" && state.google_review_url) {
    return <GoogleReviewModal url={state.google_review_url} onOpen={() => void openGoogle()} />;
  }
  return (
    <Modal title="Thank you">
      <p className="text-sm text-stone-600">
        Thank you for sharing your feedback. We appreciate you taking the time to tell us about your experience.
      </p>
    </Modal>
  );
}

function GoogleReviewModal({ url, onOpen }: { url: string; onOpen: () => void }) {
  return (
    <Modal title="Share a Google review?">
      <p className="text-sm text-stone-600">Would you like to share your experience in a Google review?</p>
      <a
        href={url}
        target="_blank"
        rel="noopener noreferrer"
        onClick={onOpen}
        className="mt-5 inline-flex rounded-md bg-teal-700 px-4 py-2 text-sm font-medium text-white"
      >
        Write a Google review
      </a>
    </Modal>
  );
}

function Modal({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-stone-900/50 p-4" role="presentation">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="review-dialog-title"
        className="w-full max-w-md rounded-xl border border-stone-200 bg-white p-6 shadow-2xl"
      >
        <h1 id="review-dialog-title" className="text-lg font-semibold text-stone-900">
          {title}
        </h1>
        <div className="mt-4">{children}</div>
      </div>
    </div>
  );
}
