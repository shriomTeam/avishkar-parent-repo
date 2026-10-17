# Reviews (The 5-Star Machine)

Patients rate a completed visit on Avishkar. A rating of 4 or 5 stars is shown the practice's Google review link. A lower rating stops there and becomes a follow-up for the practice.

This is local and ready to exercise. It is not wired to an EMR, and it does not publish the review on Google for the patient.

## What is built

Staff open **Reviews** at `/reviews`. The page uses its own workspace shell (the same kind of sidebar as Voice Receptionist). From there they can:

- Save the Google Business listing name and review link. Nothing is sent until this link is saved.
- Create a campaign and activate it. The campaign chooses SMS or email and how many minutes to wait after the visit.
- See how many requests are waiting, how many were sent, and how many ratings came back.
- See follow-ups for 1–3 star ratings and mark one resolved.

Patients open a private link, `/reviews/r/{token}`. They do not sign in. They pick 1–5 stars and can add a comment.

- 4 or 5 stars: a second screen offers a button to the stored Google review link. The Google form opens empty. Avishkar cannot prefill the stars or the comment.
- 1, 2, or 3 stars: a thank-you screen. The Google link is not shown. A follow-up row is created.

Completing an appointment is `POST /appointments/{id}/complete`. That sets the appointment status to `completed` and emits `appointment.completed` once. Reviews listens for that event. Calling complete again does not send another event. A cancelled or no-show appointment cannot be completed.

A request is scheduled only when the campaign is active, the practice is `active` or `trial`, the Google link is connected, the patient can be contacted on the chosen channel, and they have not already been asked by this campaign in the last 30 days. Reply STOP cancels a request that is still waiting.

A worker job, `dispatch_due`, runs about once a minute and hands due requests to the shared SMS and email engine. The message includes the patient's private link.

Tables live in the `reviews` schema: campaigns, the Google profile, review requests, feedback, and follow-up tasks. Patient data stays in `core`.

## What is not built

- No live EMR connector. CSV, Excel, and a read-only SQL import can load patients and appointments. Importing a past "checked out" visit stores `completed` but does not emit `appointment.completed`, so it does not start a review.
- Nothing written in Avishkar is written back to an EMR.
- The dashboard does not list each rating and comment yet. Those rows are stored.
- With `MESSAGING_PROVIDER=console`, texts are printed in the worker log. They are not delivered to a phone.

## Automated tests

From the repo root, with the test database URLs pointed at a disposable migrated database:

```bash
pnpm --filter @clinic/feature-reviews test
```

The tests cover a request scheduled once, a low rating that creates a follow-up and hides the Google link, a high rating that returns the Google link, and a patient who has opted out.

## Test it in the browser

1. Start Postgres and apply migrations.

   ```bash
   pnpm db:up
   pnpm db:migrate
   ```

   Local Docker Postgres in this checkout is on port **5433** when `POSTGRES_PORT=5433`. The four `DATABASE_*` URLs in `.env` must use that port.

2. Start the API, worker, and web app (`pnpm dev`). Sign in with Google and finish clinic onboarding. New clinics are `trial`, and Reviews is available on a trial.

3. Open `http://localhost:3000/reviews`.

   - Listing name: the practice name.
   - Review link: the real Google review URL, for example `https://g.page/r/…/review`.
   - Save the link. The green card should say the link is ready.
   - Create a draft campaign (delay `0` and SMS is fine) and activate it if it is not already active.

4. Mark a visit complete. The patient needs a phone number and SMS consent, because the campaign sends SMS. From the API, as that clinic:

   ```http
   POST /appointments/{appointment_id}/complete
   ```

   Within about a minute the worker logs the message. Copy the `/reviews/r/…` link from that log.

5. Open the link in a private window.

   - Submit **5** stars and a comment. The next screen should offer the Google button. The button opens Google's own form, blank.
   - Use a second completed appointment and submit **2** stars. The screen should thank the patient and stop. Back on `/reviews`, that rating should appear under patients not sent to Google.

6. Refresh `/reviews` and confirm the waiting, sent, and ratings counts moved.
