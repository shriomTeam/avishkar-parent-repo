# Google sign-in end to end: FastAPI implementation plan

## Outcome and scope

Implement task 3 of `docs/1_week_plan.md`: a real Google account can sign in, get an application session, create its first workspace, access the dashboard, remain signed in after refresh, and sign out with immediate server-side session revocation.

All backend application code, migrations, backend tests, dependency definitions and backend setup documentation belong under `backend/`. Next.js remains responsible for the interface and route rendering in `frontend/`. Authentication policy, token verification, user creation, sessions and workspace authorization belong to FastAPI, not Next.js.

Implementation status: FastAPI authentication, PostgreSQL sessions, protected Next.js routes and persisted workspace onboarding are implemented on `google/signin`. Setup instructions are in `backend/README.md`. Automated tests use signed tokens and a simulated provider; The user has configured Google OAuth credentials and verified real local Google login. Production HTTPS acceptance is still pending. Do not mark the weekly task complete until the real Google browser flow passes.

Agent, number, call and tool APIs remain subsequent milestones. Authenticating a user does not make the current sample dashboard data live.

## Recommended design

- Google OpenID Connect authorization-code flow through FastAPI, using Authlib for protocol handling and ID-token verification.
- Request only `openid email profile`. No Calendar, Gmail or Drive access, offline access or refresh tokens for this login milestone.
- Use Postgres for users, Google identities, workspace membership, OAuth transactions and revocable application sessions. No Redis dependency needed initially.
- Use a random opaque application session token in an HttpOnly cookie; store only its SHA-256 hash in Postgres. The session is distinct from Google's ID/access tokens.
- Same public origin for frontend and API. Locally, Next.js rewrites `/api/v1/*` to FastAPI on port 8000. In production, the HTTPS reverse proxy sends that prefix directly to FastAPI and other paths to Next.js.
- No browser localStorage tokens and no separate NextAuth/Auth.js authentication system. Next.js's rewrite and server-side session lookup are transport/rendering responsibilities only.

## Prerequisites: what we need

| Requirement | Purpose | When needed |
| --- | --- | --- |
| Google Cloud project and permission to configure Google Auth Platform | Create the web OAuth client | Before real Google testing |
| App name and support/developer contact email | Configure branding/consent | During Google setup |
| Audience choice: External or organization-only Internal if applicable | Decide which Google accounts may sign in | During Google setup |
| Development Google accounts allowed by the configured testing audience | Real browser acceptance testing | Before callback testing |
| Web OAuth client ID and client secret | Google authorization/token exchange | Backend environment only |
| Consistent local hostname and exact callback URI | Prevent cookie/redirect mismatch | Before integration |
| Python, dependency manager, Docker and Postgres | Run backend and database | Backend setup |
| Production domain, HTTPS and production client configuration | Public pilot | Before deployment |

Use `http://localhost:3000` consistently for local authentication. Register `http://localhost:3000/api/v1/auth/google/callback` as the development callback. If retaining the existing `127.0.0.1` preview address, register and configure that exact origin/callback separately rather than mixing hostnames during a flow. Google requires the redirect URI to match the authorized URI exactly.

For production, register `https://<actual-domain>/api/v1/auth/google/callback`. The production domain is still to be supplied. Prefer separate development and production OAuth clients. Check the configured audience/publication requirements before allowing users beyond the development testers; do not assume that setting a client secret makes the app publicly available.

A service account is not a substitute for a web OAuth client. No paid speech/model credentials are needed for this milestone. Keep the client secret in an ignored `backend/.env` locally and the deployment secrets store later, never in frontend env variables or source control.

## Step 1: establish backend structure and tooling

Use a feature-based modular monolith. Routes parse requests and set responses; services implement policy; repositories access the database. Shared authentication dependencies can be reused by future agents/calls modules.

```text
backend/
  pyproject.toml
  <dependency lockfile>
  .env.example
  .gitignore
  Dockerfile
  compose.yaml                 # local database/backend services
  alembic.ini
  migrations/
    env.py
    versions/
  app/
    __init__.py
    main.py                    # app factory/lifespan/router registration
    api/
      router.py                # /api/v1 router
      dependencies.py          # current user/session/workspace dependencies
    core/
      config.py                # validated environment configuration
      errors.py                # stable public errors
      logging.py               # redacted request/audit logging
      security.py              # random tokens, hashing, cookie and CSRF helpers
    db/
      base.py
      session.py               # async SQLAlchemy engine/session dependency
    modules/
      auth/
        router.py
        schemas.py
        models.py              # identities, sessions, OAuth transactions
        repository.py
        service.py
        google.py              # Authlib/provider integration
      users/
        models.py
        schemas.py
        repository.py
      workspaces/
        router.py
        models.py
        schemas.py
        repository.py
        service.py
  tests/
    conftest.py
    unit/
    integration/
  README.md
```

Dependencies: FastAPI, Uvicorn, Pydantic Settings, SQLAlchemy async, asyncpg, Alembic, Authlib and HTTPX. Tests use pytest, pytest-asyncio and mocked provider HTTP responses. Lock compatible versions during setup; do not manually pin FastAPI's transitive Starlette to an incompatible version. Ruff handles backend lint/format checks.

Configure readiness/liveness endpoints, database initialization through migrations, trusted hosts and trusted proxy settings. Database readiness must not depend on Google being available. Bind FastAPI to loopback locally; production access goes through the reverse proxy.

Exit: backend starts, health endpoints work, Postgres runs and the initial migration applies from an empty database.

## Step 2: configuration and Google setup

Create an example environment containing placeholders only:

- `APP_ENV`, `PUBLIC_APP_ORIGIN`, `GOOGLE_REDIRECT_URI`
- `DATABASE_URL`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`
- `SESSION_COOKIE_NAME`, `SESSION_TTL_SECONDS`, `COOKIE_SECURE`
- `OAUTH_TRANSACTION_TTL_SECONDS`, `TRUSTED_HOSTS`

Suggested policies: OAuth transaction lifetime 10 minutes and application session absolute lifetime 24 hours. These are application choices, not Google requirements. Expired sessions require sign-in again; idle extension/remember-me is deferred.

Next.js receives a server-only `BACKEND_INTERNAL_URL` for rewrites and server-side authentication checks. The browser uses relative `/api/v1` URLs. Validate production configuration at startup: HTTPS public origin, Secure cookies and matching configured callback. Construct redirects from trusted configuration, never arbitrary forwarded hosts or user-supplied URLs.

Google setup sequence:

1. Select/create the Cloud project.
2. Configure Google Auth Platform branding and contacts.
3. Configure the audience and add applicable development testers.
4. Configure the minimal identity scopes.
5. Create a Web application OAuth client.
6. Add the exact authorized callback above. For this server redirect flow, browser JavaScript origins are not a replacement for redirect URIs; configure them only if later introducing Google Identity Services JavaScript.
7. Put the issued credentials in the backend environment and restart the backend.
8. Confirm the actual sign-in URL, public origin and Google redirect URI use the same hostname.

Exit: the app can construct Google's authorization request using the configured web client.

## Step 3: database and identity rules

| Table | Fields and constraints |
| --- | --- |
| `users` | UUID, email, display name, optional avatar URL, active/disabled status, created/updated/last-login timestamps |
| `auth_identities` | UUID, user FK, provider, subject, email_verified; unique `(provider, subject)` |
| `workspaces` | UUID, name, timezone, optional callback phone, created/updated timestamps |
| `workspace_memberships` | User FK, workspace FK, role, active status; unique `(user_id, workspace_id)` |
| `auth_sessions` | UUID, unique token hash, user FK, created/expires/revoked timestamps, CSRF token hash |
| `oauth_transactions` | UUID, unique state hash, browser-binding token hash, nonce, PKCE verifier, expiry and consumed status |

Google `sub` is the identity key; email is profile data and must not be the account matching key. Validate `email_verified`; do not automatically merge accounts based on matching email. Database constraints and transactional upserts must handle concurrent callbacks without creating duplicate users.

Keep OAuth transaction secrets server-side, restrict DB access and promptly delete expired/consumed transaction material. Retain no Google access/ID tokens after extracting verified identity information for login.

First sign-in creates a user/identity, not a sample clinic membership. A user without a workspace is sent to onboarding. Creating a workspace and owner membership is one transaction. Enforce an initial one-workspace onboarding policy transactionally to prevent double submits creating multiple workspaces. Invite/join and workspace switching are later features.

Exit: repository tests establish unique identities, safe concurrent creation, session lookup and tenant membership checks.

## Step 4: API contract and OAuth flow

| Method/path | Result |
| --- | --- |
| `GET /api/v1/auth/google/login` | Create a short-lived login transaction and redirect to Google |
| `GET /api/v1/auth/google/callback` | Verify callback, authenticate user, create session cookie and redirect to app |
| `GET /api/v1/auth/me` | Return real user, memberships, default workspace, onboarding flag and session CSRF token; unauthenticated requests get 401 |
| `POST /api/v1/auth/logout` | Revoke current session, clear cookie; return 204 |
| `POST /api/v1/workspaces` | Authenticated, CSRF-protected initial workspace creation and owner membership |
| `GET /api/v1/health/live` | Process health |
| `GET /api/v1/health/ready` | Database readiness |

Implementation sequence for login:

1. Generate cryptographically random state, nonce, PKCE verifier/challenge and browser-binding token.
2. Persist a login transaction with expiry; set an HttpOnly, SameSite=Lax browser-binding cookie so another browser cannot complete the transaction using a copied callback URL.
3. Send state, nonce, S256 challenge, configured callback and minimal scopes to Google's discovered authorization endpoint. Use a maintained library for protocol/token validation rather than custom JWT decoding.
4. Callback validates transaction expiry, state and browser binding, and atomically claims the transaction so it cannot be replayed. The Google denial/error path also validates and clears the matching transaction.
5. Exchange the code server-side with the configured client credentials and PKCE verifier. Use bounded HTTP timeouts. A failed exchange requires restarting sign-in, not blindly replaying a consumed code.
6. Validate ID-token signature, issuer, audience, expiry, nonce and relevant authorized-party claims. Read profile only from verified claims. Never accept browser-supplied identity details as proof.
7. Upsert user and Google identity transactionally. Reject disabled users. Create a fresh opaque application session; rotate/revoke an existing session presented by this browser after successful login.
8. Set the application cookie, clear transient login data, and redirect with 303 to `/onboarding` or `/dashboard` according to membership.
9. Return an allowlisted public error code on failure; never put tokens, raw Google errors or personal information into redirect URLs. Return targets are fixed initially to avoid open redirects.

Use Google's discovery document and supported signing keys through Authlib. Verify the chosen integration supports our DB-backed state/nonce/PKCE transaction store; adapt its transaction persistence explicitly. Authlib's simple signed-cookie examples are references, not a reason to put application sessions or Google tokens into a readable cookie. Test concurrent login tabs and define a clear restart behavior if a new attempt replaces the browser-binding cookie.

## Step 5: session and authorization policy

Production session cookie: HttpOnly, Secure, SameSite=Lax, Path=/ and no Domain attribute. A `__Host-` cookie name is appropriate in HTTPS production; use an unprefixed development name when Secure is disabled for local HTTP. Cookie expiry matches server expiry. Clear cookies with matching name/path/domain settings.

- Session lookups check expiry, revocation, user status and active membership. A random cookie alone is insufficient.
- Each authenticated write requires a per-session CSRF token in `X-CSRF-Token`, plus validation of the configured Origin (or trusted Referer fallback). OAuth state protects the login callback separately; SameSite alone is not the complete write protection.
- `/auth/me` returns a session-specific CSRF token for client memory. Never cache the response: `Cache-Control: no-store` and disable frontend fetch caching. CSRF tokens are not authentication tokens.
- Logout is POST, revokes the DB session and clears the cookie. Replaying the old cookie must fail. Logout signs out of Avishkar, not the user's Google account.
- Reusable dependencies: `get_current_session`, `get_current_user`, `require_workspace_member`, and `require_workspace_role`. Workspace IDs from clients never bypass membership checks.
- Do not enable wildcard credentialed CORS. The recommended same-origin route avoids browser CORS configuration. If architecture changes to cross-origin later, separately configure explicit origins and cookie policies.
- Add rate limits for login starts/callbacks and authenticated workspace creation. Single-process local limits are acceptable for development; shared/proxy-backed limits are needed across production workers.
- Redact cookies, authorization codes, state, tokens and secrets from application and reverse-proxy logs. Use non-sensitive event categories for login success/failure/logout and session revocation.

Exit: unauthenticated API requests get 401, valid sessions work, revoked/expired sessions fail, cross-user workspace requests get 403 and missing/invalid CSRF blocks writes.

## Step 6: integrate the existing frontend

1. Replace Continue with Google's direct dashboard link with full-page navigation to `/api/v1/auth/google/login`.
2. Add a typed auth client/provider separate from the current DemoProvider. It loads `/auth/me`, handles pending/error/401 states and exposes real account information.
3. Protect dashboard and onboarding on the server by calling FastAPI `/auth/me` with the incoming Cookie header and `cache: 'no-store'`. Next.js checks no identity itself; FastAPI remains authoritative. Do not expose the internal backend URL to browser code.
4. Redirect anonymous dashboard visitors to login; users needing workspace setup to onboarding; existing members away from onboarding to dashboard. On backend unavailability, show retry rather than pretending the user is logged out or entering a redirect loop.
5. Replace Jamie Davis, JD and the account email in the sidebar/Settings with the verified user's name, initials and email. Use initials first; remote avatars can be deferred.
6. Replace Settings' sign-out link with a POST logout action including CSRF. On success, clear auth and demo state, navigate to login and refresh the router so cached layouts do not reveal the previous account. On failure, show retry and keep the current UI honest.
7. Submit onboarding to the FastAPI workspace endpoint and load actual workspace identity. Remove the public preview-setup bypass in authenticated mode.
8. Keep agents/calls/tools clearly marked sample data during this milestone. Remove seeded Jamie/Robin team membership claims; display actual current membership or a clearly separate sample section. Reset demo must never reset authentication or real workspace data.
9. Handle subsequent API 401s consistently by clearing stale client identity and requesting sign-in. A client route guard is convenience, not API authorization.
10. Update UI text, README and Playwright tests: login is real, remaining dashboard operations are simulated. Real mode must not silently fall back to a demo session.

Exit: a fresh browser completes Google sign-in and sees its own identity; refresh and direct navigation work; anonymous access is blocked and logout clears access.

## Step 7: verification

Automated backend tests (mock Google, real disposable Postgres for integration):

- New and returning identities; duplicate/concurrent callback behavior.
- Invalid/missing/expired/replayed state and mismatched browser cookie.
- Invalid signature/issuer/audience/nonce, expired token and unverified email.
- Google denial, unavailable provider, token timeout and database failure produce safe errors without a partial authenticated session.
- Expired/revoked sessions and disabled users fail authentication.
- Logout cookie flags/deletion, cookie replay after logout and missing/invalid CSRF.
- Two users cannot access each other's workspace; double onboarding submission is safe.
- Sessions survive backend restart because they live in Postgres.

Frontend tests:

- Anonymous redirect, loading/failure states, real identity rendering, onboarding routing, logout and stale state cleanup.
- Existing static interaction tests use explicit test fixtures/mocks; do not add a production demo bypass just to make them pass.
- Check cookie propagation through the Next.js rewrite, callback redirects and server-side cookie forwarding.

Manual real-Google acceptance:

1. Fresh/incognito browser → Continue with Google → Google account selection/consent → onboarding.
2. Create a workspace → dashboard shows actual account/workspace identity.
3. Refresh and open a dashboard URL directly → same valid session.
4. Sign out in Settings → login; revisit dashboard and replay the previous cookie → denied.
5. Returning sign-in → same user/workspace without duplicates.
6. Different Google account → separate identity/workspace.
7. Cancel Google consent → readable login error and retry.
8. Repeat on HTTPS production with production cookie/client settings before public release.

Mocked tests alone do not establish Google sign-in end to end. Do not automate entry of the user's Google password or bypass Google account challenges; the user completes the provider account interaction.

## Implementation order and completion gates

| Order | Deliverable | Gate |
| --- | --- | --- |
| 1 | Backend skeleton, env validation and Postgres migration | Fresh setup boots and migrates |
| 2 | Google OAuth client configuration | Exact local callback and tester access ready |
| 3 | Identity repositories, sessions and transaction storage | Core backend tests pass |
| 4 | Login/callback/me/logout endpoints | Mocked valid/invalid provider cases pass |
| 5 | Workspace creation and membership dependencies | Isolation and onboarding tests pass |
| 6 | Next.js auth integration, real profile and logout | Frontend flows pass against backend |
| 7 | Real Google local test, deployment configuration and docs | Manual acceptance plus HTTPS checks pass |

Planning estimate: 2-3 focused engineering days for the structured auth/workspace foundation and verification, assuming OAuth credentials, local Postgres and testing accounts are ready. The one-week board's Monday target is aggressive when starting with an empty backend; update it against observed progress rather than dropping session/isolation testing.

## Definition of done

- All backend implementation lives under `backend/`; documented reproducible installation and migration commands.
- Real Google login succeeds with minimal scopes and verified identity.
- Identity and workspace membership persist in Postgres with correct uniqueness constraints.
- Server-side revocable session survives refresh/restart; secure production cookies and CSRF protections verified.
- Dashboard/onboarding routing is correct; actual account appears in sidebar and Settings.
- Sign-out revokes access; all future protected APIs have reusable user/workspace dependencies.
- No secrets/tokens in source, frontend bundles, logs or redirect URLs.
- Backend tests, frontend checks and real local/HTTPS acceptance completed; remaining dashboard mock features clearly identified.

## Inputs still needed before real integration

Google project/audience, contact email, development tester accounts, issued client credentials via local secret configuration, and the production domain. These do not block scaffolding or mock-provider tests, but actual Google acceptance depends on the configured client.

## Official implementation references

- Google server-side OIDC flow, redirect matching and subject identity: https://developers.google.com/identity/openid-connect/openid-connect
- Google OIDC protocol reference: https://developers.google.com/identity/openid-connect/reference
- Authlib Starlette/FastAPI-compatible client integration: https://docs.authlib.org/en/v1.5.2/client/starlette.html
- FastAPI modular application structure: https://fastapi.tiangolo.com/tutorial/bigger-applications/
- Starlette session/cookie middleware semantics (signed cookies are readable, not encrypted): https://www.starlette.io/middleware/
