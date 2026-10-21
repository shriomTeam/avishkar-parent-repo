# The two public services. Plain settings are environment variables below; anything sensitive is a Secret Manager
# secret that Cloud Run injects at start (see secrets.tf and modules/cloudsql for where each one comes from).

locals {
  api_secrets = {
    DATABASE_URL         = module.cloudsql.secret_ids["app-url"]
    DATABASE_SYSTEM_URL  = module.cloudsql.secret_ids["system-url"]
    DATABASE_AUTH_URL    = module.cloudsql.secret_ids["auth-url"]
    GOOGLE_CLIENT_SECRET = google_secret_manager_secret.google_client_secret.secret_id
    VOICE_SECRETS_KEY    = google_secret_manager_secret.voice_secrets_key.secret_id
  }
}

resource "google_service_account" "api" {
  account_id   = "${local.name}-api"
  display_name = "API runtime"
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
  # The database is small, so the instance count is capped. One instance stays warm so a call never waits on a cold start.
  min_instances   = 1
  max_instances   = 3
  concurrency     = 50
  timeout_seconds = 3600
  memory          = "1Gi"

  env = {
    APP_ENV                 = "production"
    PUBLIC_APP_ORIGIN       = local.web_url
    GOOGLE_CLIENT_ID        = var.google_client_id
    GOOGLE_REDIRECT_URI     = "${local.web_url}/api/v1/auth/google/callback"
    COOKIE_SECURE           = "true"
    SESSION_COOKIE_NAME     = "__Host-avishkar_session"
    CORS_ORIGINS            = jsonencode([local.web_url])
    TRUSTED_HOSTS           = jsonencode([local.api_host])
    TRUSTED_PROXY_HOPS      = "1" # Cloud Run's front end is the one proxy; see clinic_api.forwarded
    VOICE_GCP_PROJECT       = var.project_id
    VOICE_RECORDINGS_BUCKET = module.storage.name # recordings go under recordings/
  }
  secret_env = local.api_secrets

  depends_on = [
    google_project_service.apis,
    google_secret_manager_secret_iam_member.api,
    google_secret_manager_secret_version.google_client_secret,
    google_secret_manager_secret_version.voice_secrets_key,
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
