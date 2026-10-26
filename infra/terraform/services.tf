# The two public services. Plain settings are environment variables below; anything sensitive is a Secret Manager
# secret that Cloud Run injects at start (see secrets.tf and modules/cloudsql for where each one comes from).

locals {
  api_secrets = merge({
    DATABASE_URL         = module.cloudsql.secret_ids["app-url"]
    DATABASE_SYSTEM_URL  = module.cloudsql.secret_ids["system-url"]
    DATABASE_AUTH_URL    = module.cloudsql.secret_ids["auth-url"]
    GOOGLE_CLIENT_SECRET = google_secret_manager_secret.google_client_secret.secret_id
    VOICE_SECRETS_KEY    = google_secret_manager_secret.voice_secrets_key.secret_id
    }, var.invitations_enabled ? {
    SENDGRID_API_KEY             = google_secret_manager_secret.email["sendgrid-api-key"].secret_id
    EMAIL_PAYLOAD_ENCRYPTION_KEY = google_secret_manager_secret.email["email-payload-key"].secret_id
  } : {}, var.invitations_enabled ? local.email_rotation_secrets : {})

  # The ingest service reads and writes tenant data like the API does, so it gets the same production settings (the
  # shared configuration check requires them) but only the secrets it needs.
  ingest_secrets = {
    DATABASE_URL         = module.cloudsql.secret_ids["app-url"]
    GOOGLE_CLIENT_SECRET = google_secret_manager_secret.google_client_secret.secret_id
  }

  platform_env = {
    APP_ENV             = "production"
    PUBLIC_APP_ORIGIN   = local.web_url
    GOOGLE_CLIENT_ID    = var.google_client_id
    GOOGLE_REDIRECT_URI = "${local.web_url}/api/v1/auth/google/callback"
    COOKIE_SECURE       = "true"
    SESSION_COOKIE_NAME = "__Host-avishkar_session"
    CORS_ORIGINS        = jsonencode([local.web_url])
    TRUSTED_HOSTS       = jsonencode([local.api_host])
  }
}

resource "google_service_account" "api" {
  account_id   = "${local.name}-api"
  display_name = "API runtime"
}

# Runs the private ingest service.
resource "google_service_account" "ingest" {
  account_id   = "${local.name}-ingest"
  display_name = "Knowledge ingest runtime"
}

# The identity Cloud Tasks uses to call the ingest service. It can do nothing else.
resource "google_service_account" "queue" {
  account_id   = "${local.name}-queue"
  display_name = "Knowledge ingest queue caller"
}

resource "google_service_account" "web" {
  account_id   = "${local.name}-web"
  display_name = "Web runtime"
}

# The API reads only its own secrets.
resource "google_secret_manager_secret_iam_member" "api" {
  for_each = local.api_secrets

  secret_id = each.value
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.api.email}"
}

# Gemini Live runs on Vertex AI using the service account, so there is no API key to manage.
resource "google_project_iam_member" "api_vertex" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.api.email}"
}

module "api" {
  source = "./modules/cloud-run-service"

  name                  = "${local.name}-api"
  region                = var.region
  labels                = local.labels
  service_account_email = google_service_account.api.email
  vpc                   = { network = module.network.vpc_id, subnet = module.network.subnet_id }

  # Each live call is one long request, so concurrency is calls per instance, and calls can last up to an hour.
  # The database is small, so the instance count is capped. Scales to zero while we are building, so the first request
  # after idle waits for a cold start; set this to 1 before real callers use it, so a call never waits.
  min_instances   = 0
  max_instances   = 3
  concurrency     = 50
  timeout_seconds = 3600
  memory          = "1Gi"

  env = merge(local.platform_env, {
    INVITATIONS_ENABLED     = tostring(var.invitations_enabled)
    EMAIL_PROVIDER          = var.invitations_enabled ? "sendgrid" : "console"
    EMAIL_FROM_ADDRESS      = var.email_from_address
    EMAIL_FROM_NAME         = var.email_from_name
    EMAIL_REPLY_TO          = var.email_reply_to
    TRUSTED_PROXY_HOPS      = "1" # Cloud Run's front end is the one proxy; see clinic_api.forwarded
    VOICE_GCP_PROJECT       = var.project_id
    VOICE_RECORDINGS_BUCKET = module.storage.name # recordings go under voice-recordings/
    KNOWLEDGE_BUCKET        = module.storage.name # documents go under knowledge-base/
    KNOWLEDGE_GCP_PROJECT   = var.project_id
    # Uploads put a task on this queue; Cloud Tasks then calls the private ingest service as the queue account.
    KNOWLEDGE_TASKS_QUEUE         = module.knowledge_queue.name
    KNOWLEDGE_TASKS_REGION        = var.region
    KNOWLEDGE_INGEST_URL          = local.ingest_url
    KNOWLEDGE_TASKS_INVOKER_EMAIL = google_service_account.queue.email
  }, local.email_task_environment)
  secret_env = local.api_secrets

  depends_on = [
    google_project_service.apis,
    google_secret_manager_secret_iam_member.api,
    google_secret_manager_secret_version.google_client_secret,
    google_secret_manager_secret_version.voice_secrets_key,
    google_secret_manager_secret_version.sendgrid_api_key,
    google_secret_manager_secret_version.email_payload_key,
    google_secret_manager_secret_version.email_old_payload_keys,
  ]
}

module "web" {
  source = "./modules/cloud-run-service"

  name                  = "${local.name}-web"
  region                = var.region
  labels                = local.labels
  service_account_email = google_service_account.web.email

  max_instances = 3

  env = {
    PUBLIC_APP_ORIGIN    = local.web_url
    BACKEND_INTERNAL_URL = local.api_url
    NEXT_PUBLIC_API_URL  = local.api_url
  }

  depends_on = [google_project_service.apis]
}

# ---- Knowledge-base ingestion --------------------------------------------------------------------------------------
# Reading a file, splitting it and embedding it takes seconds and Vertex AI calls, so it runs outside the API: the API
# puts a task on the queue, Cloud Tasks calls this private service (and retries it), and the service scales to zero
# between uploads. It is the same code as the rest of the platform, built as its own image (apps/worker/Dockerfile).

resource "google_secret_manager_secret_iam_member" "ingest" {
  for_each = local.ingest_secrets

  secret_id = each.value
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.ingest.email}"
}

resource "google_project_iam_member" "ingest_vertex" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.ingest.email}"
}

# Reads uploaded files and deletes the old file when a document is replaced. Same scope as the API: this bucket only.
resource "google_storage_bucket_iam_member" "ingest_files" {
  bucket = module.storage.name
  role   = "roles/storage.objectUser"
  member = "serviceAccount:${google_service_account.ingest.email}"
}

module "ingest" {
  source = "./modules/cloud-run-service"

  name                  = "${local.name}-ingest"
  region                = var.region
  labels                = local.labels
  service_account_email = google_service_account.ingest.email
  vpc                   = { network = module.network.vpc_id, subnet = module.network.subnet_id }

  # Not reachable without a Google-signed token from the queue account. One file at a time per instance, and few
  # instances, because the database is small.
  public          = false
  min_instances   = 0
  max_instances   = 2
  concurrency     = 1
  timeout_seconds = 600
  memory          = "1Gi"

  env = merge(local.platform_env, {
    KNOWLEDGE_BUCKET              = module.storage.name
    KNOWLEDGE_GCP_PROJECT         = var.project_id
    KNOWLEDGE_TASKS_AUDIENCE      = local.ingest_url
    KNOWLEDGE_TASKS_INVOKER_EMAIL = google_service_account.queue.email
  })
  secret_env = local.ingest_secrets

  depends_on = [
    google_project_service.apis,
    google_secret_manager_secret_iam_member.ingest,
    google_secret_manager_secret_version.google_client_secret,
  ]
}

# The queue account may call the ingest service, and nothing else may.
resource "google_cloud_run_v2_service_iam_member" "queue_invokes_ingest" {
  name     = module.ingest.name
  location = var.region
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.queue.email}"
}

# The API may add tasks to this queue only, and may name the queue account as the caller.
resource "google_cloud_tasks_queue_iam_member" "api_enqueues" {
  name     = module.knowledge_queue.name
  location = var.region
  role     = "roles/cloudtasks.enqueuer"
  member   = "serviceAccount:${google_service_account.api.email}"
}

resource "google_service_account_iam_member" "api_acts_as_queue" {
  service_account_id = google_service_account.queue.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.api.email}"
}
