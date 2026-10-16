# Avishkar Voice AI

Next.js frontend and FastAPI backend with Google sign-in and PostgreSQL.
Google login and workspace setup are connected to the backend. Voice agents, calls, numbers and tools currently use sample data.

## What you need

- Node.js 20.9+ and npm.
- Docker with Docker Compose. Start Docker Desktop first, or run `colima start` if you use Colima.
- A Google **Web application** OAuth client ID and secret.
- Python 3.12+ only if you run FastAPI directly instead of using Docker.

## 1. First-time configuration

Run these commands from the project root **only if you do not already have the environment files**:

```bash
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env.local
```

In `backend/.env`, fill in:

```dotenv
GOOGLE_CLIENT_ID=your-client-id
GOOGLE_CLIENT_SECRET=your-client-secret
PUBLIC_APP_ORIGIN=http://localhost:3000
GOOGLE_REDIRECT_URI=http://localhost:3000/api/v1/auth/google/callback
```

Register the exact redirect URI above in Google Console. Keep credentials only in `backend/.env`.
See the [Google setup guide](BACKEND_SOURCE_README.md#1-create-the-google-oauth-client) if you need to create the client.

`frontend/.env.local` should contain:

```dotenv
BACKEND_INTERNAL_URL=http://127.0.0.1:8000
```

## 2. Start the backend and database

In your first terminal:

```bash
cd backend
docker compose up --build
```

This starts PostgreSQL and FastAPI, applies database migrations and keeps database data between restarts.
Backend: `http://localhost:8000`. API docs: `http://localhost:8000/docs`.

## 3. Start the frontend

In a second terminal, starting from the project root:

```bash
cd frontend
npm ci
npm run dev
```

Open **http://localhost:3000** and click **Continue with Google**.
Use `localhost` consistently during login; do not switch to `127.0.0.1` midway.

After the first installation, you only need `docker compose up` in `backend/` and `npm run dev` in `frontend/`.

## Run FastAPI directly with Python (optional)

Use this instead of the Docker backend when developing Python code.
From the project root:

```bash
cd backend
docker compose up -d db
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.lock
pip install --no-deps -e .
alembic upgrade head
uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000 --reload --no-access-log --no-proxy-headers
```

For the Compose database, set this in `backend/.env`:

```dotenv
DATABASE_URL=postgresql+asyncpg://avishkar:local-development@localhost:5432/avishkar
```

If you already use another PostgreSQL instance, keep its connection URL and skip `docker compose up -d db`.
The local database configured during our login test stores data under `backend/.local/postgres/`; it is separate from the Compose database. Switching databases gives you a separate set of users and workspaces.

For later starts, activate `.venv`, run `alembic upgrade head` and run the `uvicorn` command above. Your database must also be running.
Do not run both the Docker backend and Python backend on port 8000 at the same time.

## Check or stop the servers

Database and backend readiness: http://localhost:8000/api/v1/health/ready.
You should see `"status":"ready"` and `"google_configured":true`.

Press `Ctrl+C` in the frontend/backend terminal to stop that server. To stop the Docker services:

```bash
cd backend
docker compose down
```

Database data is retained. Restart the backend whenever you change its `.env` credentials.

More details: [backend guide](BACKEND_SOURCE_README.md) · [frontend guide](FRONTEND_SOURCE_README.md).
