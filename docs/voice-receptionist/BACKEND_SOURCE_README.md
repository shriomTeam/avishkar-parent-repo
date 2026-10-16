# FastAPI authentication backend

Google OpenID Connect sign-in, database sessions and first-workspace onboarding are implemented here. Voice agents, numbers, calls and tools still use frontend sample data. Real local Google login has been verified by the user. Production HTTPS validation remains pending.

## 1. Create the Google OAuth client

1. Open [Google Cloud Console](https://console.cloud.google.com/) and select/create a project.
2. Open Google Auth Platform. Complete Branding with app name, support email and developer contact. Choose the appropriate Audience (External for ordinary Google accounts; Internal only for your organization). For development, configure testing access and add your intended test accounts if required by your audience settings.
3. In Clients, create an OAuth client of type **Web application**. Name it Avishkar local development.
4. Add this exact Authorized redirect URI: `http://localhost:3000/api/v1/auth/google/callback`. This server redirect flow does not need a browser JavaScript origin entry.
5. Put the client ID and secret in the ignored `backend/.env` as `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`. Never put the secret in frontend variables, git, screenshots or chat.
6. Request only `openid email profile`; no Google API enablement or speech/model credentials are needed for this milestone. Before public rollout, review the audience, publication and branding requirements in your Console.

Use `http://localhost:3000` throughout a login. To use `127.0.0.1`, register its exact callback separately and change both `PUBLIC_APP_ORIGIN` and `GOOGLE_REDIRECT_URI` to match. See Google's [web server setup](https://developers.google.com/identity/protocols/oauth2/web-server) and [OpenID Connect documentation](https://developers.google.com/identity/openid-connect/openid-connect).

## 2. Run locally

Requires Python 3.12+, Node compatible with the frontend and Docker with Compose.

From `backend/`:

```bash
cp .env.example .env
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.lock
pip install --no-deps -e .
docker compose up -d db
alembic upgrade head
uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000 --no-access-log --no-proxy-headers
```

Fill Google credentials in `.env` before testing real sign-in. Without them, login shows a configuration error rather than letting someone enter as a demo user. If using an existing PostgreSQL instance, set its asyncpg URL and skip the Compose database step.

In a second terminal from `frontend/`:

```bash
cp .env.example .env.local
npm ci
npm run dev
```

Open `http://localhost:3000`. Next forwards `/api/v1/*` to the backend. `BACKEND_INTERNAL_URL` is server-only. Alternatively, `docker compose up --build` runs database and backend together; run the frontend separately.

`GET /api/v1/health/live` checks the process. `GET /api/v1/health/ready` checks the migrated database and reports `google_configured`; a missing migration returns 503. Swagger is at `/docs` only outside production.

## Code structure and contracts

- `app/api`: API registration and reusable session, CSRF, membership and role dependencies.
- `app/core`: validated settings, cookies, token hashes and safe audit categories.
- `app/db`: SQLAlchemy base, connection/session factory and model registration.
- `app/modules/auth`: Google discovery/token validation, OAuth transactions, opaque sessions, rate limits and auth routes.
- `app/modules/users`: Google-subject identity provisioning. Same email with a different Google subject never merges users.
- `app/modules/workspaces`: atomic first workspace and owner membership creation.
- `migrations`: Alembic schema migrations. Run migrations before starting workers.
- `tests`: signed-token tests, PostgreSQL integration tests and a test-only browser provider.

Routes: GET `/api/v1/auth/google/login`, GET `/api/v1/auth/google/callback`, GET `/api/v1/auth/me`, POST `/api/v1/auth/logout`, POST `/api/v1/workspaces`, GET `/api/v1/workspaces/{id}`. Writes require the `/me` CSRF token in `X-CSRF-Token` plus a matching Origin (or same-origin Referer). No CORS is needed because the public browser origin is shared.

Session tokens are random opaque values; only hashes are stored. Cookies are HttpOnly, SameSite=Lax, Path=/ and host-only. Sessions expire after 24 hours by default and logout revokes them immediately. OAuth transactions expire after 10 minutes and require the browser binding cookie, state, nonce and PKCE. Google tokens are verified against cached Google public keys and discarded. Rate limiting uses PostgreSQL, so it works across backend workers. Expired rows are swept on new login attempts; active sessions always check expiry.

## Validation

From `backend/`, with a **disposable**, migrated PostgreSQL database (tests insert persistent records):

```bash
ruff check .
ruff format --check .
pytest tests/unit -q
TEST_DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/avishkar_test pytest -q
alembic check
```

For browser tests, migrate that test database by temporarily supplying its URL as `DATABASE_URL`, then from `frontend/`:

```bash
TEST_DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/avishkar_test npm run test:e2e
```

Stop any existing Next dev process for this checkout first. Playwright starts isolated ports 3100 and 8001. `tests/browser_server.py` injects a simulated provider solely in that test entry point; production `app.main` has no simulated sign-in route. Browser tests exercise real FastAPI sessions and onboarding, while unit tests validate signed OIDC claims. They do not prove Google's real consent/token exchange.

Manual acceptance after configuring credentials:

1. Sign in with a fresh Google account; create a workspace; confirm actual name/email and workspace in Settings.
2. Refresh, restart FastAPI and open the dashboard again; verify persisted session and workspace.
3. Sign out; refresh or revisit a dashboard route; it must return to login. Sign back in; workspace must remain.
4. Cancel the Google prompt and retry. Test a second account with its own workspace. Confirm sample voice features are still labeled as sample data.
5. On a staging HTTPS domain verify Secure/__Host cookies and the same steps before production.

## Production configuration

Use separate production OAuth credentials and register `https://your-domain/api/v1/auth/google/callback`. Set `APP_ENV=production`, `PUBLIC_APP_ORIGIN`, matching `GOOGLE_REDIRECT_URI`, `COOKIE_SECURE=true`, `SESSION_COOKIE_NAME=__Host-avishkar_session`, a production database URL and explicit JSON `TRUSTED_HOSTS` including the public/internal proxy hostnames. Store secrets in the deployment secrets manager. Settings reject insecure production configurations.

Terminate TLS at a trusted proxy and route `/api/v1/*` directly to FastAPI. Keep backend port private; preserve the public Host. For accurate per-client rate limiting behind a proxy, enable Uvicorn proxy headers only with `--forwarded-allow-ips` set to that proxy's actual trusted address/network; never trust arbitrary forwarded headers. Without this, limits group requests under the proxy IP. Keep proxy/access logging disabled or redact auth callback query strings and Cookie headers; this app's audit logs only emit categories. Limit request sizes/timeouts at the proxy. Disable query logging at the database/observability layer as well.

Real local Google login has passed user acceptance. Complete production HTTPS validation before deployment.
