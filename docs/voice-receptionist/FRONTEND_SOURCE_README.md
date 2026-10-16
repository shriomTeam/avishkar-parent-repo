# Avishkar Voice frontend

A Next.js App Router / React / TypeScript migration of the supplied Avishkar dashboard. Google sign-in, database sessions and workspace onboarding use the FastAPI backend. Dashboard routes require a valid session. Agents, calls, numbers, tools and retention actions remain simulated. See [backend setup and Google OAuth instructions](BACKEND_SOURCE_README.md) before running the frontend.

## Run locally

Requires Node.js 20.9 or newer compatible with the locked Next.js version, and npm.

```bash
cd frontend
npm ci
cp .env.example .env.local
npm run dev
```

Open http://localhost:3000. The root route redirects to `/login`.

```bash
npm run lint
npm run typecheck
npm run build
npm start
```

`npm run build` creates a production Next.js app, including on-demand agent/call detail routes. “Static dashboard” here means a frontend backed by fixtures, rather than a static HTML export.

## Demo behavior

- Shared state survives client-side navigation. Refreshing the page or reopening the app restores the fixtures. Settings → Reset demo also restores them.
- Create/edit agents, save drafts and publish immutable version snapshots. Existing call labels/version references remain unchanged when an agent is edited.
- Connect sample numbers, assign published agents, configure tools and variables, and save sample privacy preferences.
- Test studio uses the saved draft. It displays a scripted conversation and saves a draft test call labeled v0. It does not evaluate prompts, access the microphone, contact providers or execute endpoints.
- Recording previews animate a waveform without audio. No recording asset was supplied.
- Call history supports search, agent/status filters and CSV export of filtered records, with spreadsheet formula protection.
- Overview metrics come from the same call fixtures. Its date range ends at the latest sample/session call. Chart dates use UTC; call timestamps use the selected workspace timezone.
- Tools validate JSON input-schema structure and show simulated results. Settings displays your authenticated membership; inviting teammates is a future milestone. Retention preferences do not delete data.
- Form errors, missing records, empty results, loading state and service failure messaging are included.

## Structure and backend handoff

- `src/app`: route entries, metadata and layouts.
- `src/components`: React feature screens and shared UI components.
- `src/lib/types.ts`: named domain types.
- `src/lib/demo/seed.ts`: sample fixtures and scripted transcript builder.
- `src/lib/demo/provider.tsx`: shared state, loading/errors and action feedback.
- `src/lib/services/dashboard.ts`: async adapter boundary.
- `src/lib/services/mock-dashboard.ts`: local command handling.

Replace the mock service boundary when the backend contract is agreed. Authentication and workspace authorization are enforced by FastAPI; browser sample state does not authorize access. Backend credentials must stay server-side. Agent versions, call events, tool execution and retention need real server semantics before being presented as live features.

The original source remains untouched in Downloads. Provider/model names are sample design content rather than provider selection decisions.

## Browser tests

```bash
TEST_DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/avishkar_test npm run test:e2e
```

Playwright uses installed Google Chrome (`channel: 'chrome'`) and starts isolated Next and FastAPI servers on ports 3100/8001. Stop existing Next dev for this checkout first and migrate a disposable PostgreSQL database as described in the backend README. The browser provider is test-only; real Google acceptance remains a manual check. Tests cover Google-only login, all routes at desktop/tablet/mobile widths, create/publish/route/test journeys, variable validation, tool validation, call filters/downloads, missing records, dialog focus and keyboard tabs. To use Playwright Chromium instead, install its browser and remove `channel: 'chrome'` from the config.

`npm run format` formats source; `npm run format:check` checks formatting.
