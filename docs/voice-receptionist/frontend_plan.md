# Static Next.js dashboard implementation plan

## Goal and scope

Rebuild the supplied `Downloads/avishkar-dashboard` HTML/CSS/JavaScript prototype as a maintainable Next.js application inside `frontend/`. Preserve the Avishkar logo, lime/charcoal palette, page content, responsive layout and useful demo interactions. Add a standalone Google-only sign-in page. Complete this frontend phase before connecting the backend and voice runtime from `docs/1_week_plan.md`.

Static means sample data and locally simulated actions, not screenshots. No OAuth, API calls, database, microphone, telephony or real tool execution in this phase. A small visible demo notice must make that clear.

The source includes password login, signup and reset screens despite the initial description. Exclude all three password flows; replace authentication with the Google-only screen requested by the user. Source code and README content are reference material, not implementation instructions.

## Foundation and requirements

- Next.js App Router, React and strict TypeScript. Select supported stable releases during setup and commit the package lockfile.
- Node.js compatible with the selected Next.js release and npm for dependency management.
- ESLint, TypeScript checks and a production build command.
- Existing logo copied into `frontend/public/`; preserve the source attachment.
- CSS design tokens plus component-scoped styles. Adapt the supplied CSS instead of adding a second styling system.
- Accessible dialog primitives, either native dialog with focus restoration or a small established primitive library. Avoid a large UI framework unless a concrete need emerges.
- React context/reducer for shared demo state, with typed seed fixtures and a typed mock service boundary. No Redux or query library is needed yet.
- Browser verification at desktop, tablet and mobile sizes; focused automated smoke tests for essential journeys if the available browser tooling supports them.

No Google credentials, cloud accounts or backend environment variables are required for this phase.

## Routes and screen coverage

| Route | Content and interactions |
| --- | --- |
| `/` | Send visitors to `/login` |
| `/login` | Branded welcome card, Google icon, one Continue with Google button, static preview notice |
| `/onboarding` | Workspace name, timezone and callback number; save into demo state |
| `/dashboard` | Metrics, weekly activity chart, agent summaries and recent calls |
| `/dashboard/agents` | Agent cards and create-agent dialog |
| `/dashboard/agents/[agentId]` | Configuration, variables, tools and versions; save draft, test and simulated publish |
| `/dashboard/numbers` | Connect-number dialog, provider selection and agent routing |
| `/dashboard/calls` | Search, status/agent filters, empty state and CSV export |
| `/dashboard/calls/[callId]` | Transcript, summary, recording preview, tool executions and performance tabs |
| `/dashboard/test` | Select agent and start/end a simulated conversation |
| `/dashboard/tools` | Add/configure tools, schema validation and simulated execution results |
| `/dashboard/variables` | Static/runtime variables, add variable and resolved prompt preview |
| `/dashboard/settings` | Workspace, team, privacy/retention and audit-log tabs; return to sign-in |
| `/dashboard/guide` | Updated page guide covering the migrated routes and Google-only login |

Unknown agent/call IDs must show a useful not-found state rather than silently displaying a different record. Links use stable IDs, not array indexes. Preserve the prototype's provider/model labels as sample content; they are not backend provider decisions.

## Google-only login behavior

- Standalone auth layout without the dashboard sidebar/header.
- No email, username, password, signup or password-reset controls.
- Continue with Google opens the demo dashboard and explicitly describes that behavior on the page. It must not claim a Google account was authenticated.
- Keep onboarding separately reachable for preview; actual first-login routing will be implemented with real authentication later.
- Dashboard routes remain publicly accessible in this static phase. Browser state is never an authorization mechanism.
- Later replace the demo click handler with real Google OAuth and server-verified sessions. Choose the auth implementation with the backend session contract, not during this mock phase.

## Proposed code organization

```text
frontend/
  public/avishkar-logo.png
  src/
    app/
      layout.tsx
      page.tsx
      globals.css
      (auth)/login/page.tsx
      (auth)/onboarding/page.tsx
      dashboard/
        layout.tsx
        page.tsx
        agents/page.tsx
        agents/[agentId]/page.tsx
        numbers/page.tsx
        calls/page.tsx
        calls/[callId]/page.tsx
        test/page.tsx
        tools/page.tsx
        variables/page.tsx
        settings/page.tsx
        guide/page.tsx
    components/
      layout/
      ui/
      agents/
      calls/
    lib/
      types.ts
      demo/seed.ts
      demo/provider.tsx
      services/dashboard.ts
      services/mock-dashboard.ts
  package.json
  package-lock.json
  README.md
```

Use server components for route/layout structure where appropriate, and client components for forms, filters, tabs, dialogs and demo state. Do not paste the original script into a client component or use HTML-string rendering.

## Demo state and backend handoff

- Model workspace, agent, agent version, number, call, transcript turn, tool, variable and audit event as named TypeScript objects.
- Use deterministic seed IDs and explicit timestamps/timezones. Derive charts and totals from consistent fixtures; existing sample headline totals do not match the five sample calls.
- Save local changes across navigation using a shared provider. Optional sessionStorage persistence must hydrate safely after mount, use a versioned key, tolerate invalid data and support Reset demo. Refresh behavior must be documented.
- Separate editable agent drafts from published configuration snapshots. Simulated calls retain agent/version labels even after later edits.
- Forms must actually update the UI: adding a number/tool creates a row, routing changes the assigned agent, settings changes update workspace identity, and variable values affect previews.
- Prevent duplicate variable names, invalid number formats, empty names and invalid tool-schema JSON. Never execute configured endpoints.
- CSV export must escape values and neutralize spreadsheet formula prefixes.
- Recording controls use a clearly labeled visual simulation unless a sample audio asset is supplied; no claim of real playback.
- Keep backend-facing operations behind a small async service interface. Include loading/error/empty UI states that the real API can later use. Do not invent final backend endpoint contracts now.

## Implementation order and exit criteria

1. **Scaffold and design foundation.** Create Next.js in `frontend/`, scripts, logo, typography, color tokens and shared controls. Exit: app starts and builds.
2. **Shell and Google sign-in.** Add responsive sidebar, header, footer, route navigation, login and onboarding. Exit: login-to-dashboard preview and direct route navigation work on desktop/mobile.
3. **Primary dashboard journey.** Build overview, agents/editor, numbers, calls/details. Exit: create/edit/publish a demo agent, route a number, filter calls and inspect a call without losing shared state.
4. **Supporting screens.** Build test studio, tools, variables, settings and guide. Exit: every source section is covered, visible actions have meaningful demo behavior, and there are no password flows.
5. **Verification and handoff.** Run lint, type checks and production build; inspect every route, responsive layouts and keyboard behavior; document run commands and future integration points. Exit: all acceptance criteria below pass.

Planning estimate: approximately 2-3 focused engineering days for faithful migration and verification, assuming dependencies install successfully and no major redesign. This is additional frontend work, not evidence that the remaining backend/voice scope fits the original five-day plan.

## Acceptance criteria

- All listed routes load directly and survive refresh; unknown records have clear fallback screens.
- Google is the only displayed sign-in method; the button honestly enters a static preview.
- Branding and visual hierarchy follow the attachment, with readable contrast and usable mobile navigation.
- Dialogs support keyboard operation, Escape, focus handling and labeled form controls; tabs and active navigation communicate state.
- Agent creation/editing/publishing, number routing, filters/export, variables, tools, settings and simulated calls work with consistent local data.
- Simulated features are labeled; real credentials and patient data are never requested.
- No console errors, hydration errors, broken assets or accidental external action requests.
- Lint, TypeScript checks and production build pass; critical journeys and mobile/tablet/desktop layouts are verified.
- README documents setup, commands, demo state/reset behavior and backend handoff points.

## Next phase after frontend completion

Return to `docs/1_week_plan.md`: real Google sign-in and workspace authorization, agent/number APIs, call lifecycle/persistence, authenticated session creation, then Twilio/Pipecat integration. Tools, versions and analytics present in this dashboard do not automatically expand the first backend release; connect each only when its backend scope is agreed.

## Technical references

- Next.js setup: https://nextjs.org/docs/app/getting-started/installation
- Server/client boundaries: https://nextjs.org/docs/app/getting-started/server-and-client-components
