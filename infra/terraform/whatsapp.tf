# The WhatsApp agent runs as its own public Cloud Run service, so patient chat traffic (and the slow calls to the model
# and to Meta) never compete with the clinic's own API and web traffic. It is the same voice feature code, built as its
# own image (apps/whatsapp/Dockerfile). Staff screens and the chat history stay in the main API; both read the
# same tables. Everything here is off until `whatsapp_enabled` is true.

locals {
  whatsapp_host = "${local.name}-whatsapp-${data.google_project.this.number}.${var.region}.run.app"
  whatsapp_url  = "https://${local.whatsapp_host}"

  # Meta's app secret and verify token come from outside (GitHub production secrets -> TF_VAR_* -> Secret Manager).
  whatsapp_external_secrets = var.whatsapp_enabled ? {
    VOICE_WHATSAPP_APP_SECRET   = google_secret_manager_secret.whatsapp["app-secret"].secret_id
    VOICE_WHATSAPP_VERIFY_TOKEN = google_secret_manager_secret.whatsapp["verify-token"].secret_id
  } : {}

  # Only what the service needs. It looks up the clinic from the number that was written to with the system role, then
  # works as that clinic. The key that encrypts every clinic's messages is the same one the API uses.
  whatsapp_secrets = var.whatsapp_enabled ? merge({
    DATABASE_URL         = module.cloudsql.secret_ids["app-url"]
    DATABASE_SYSTEM_URL  = module.cloudsql.secret_ids["system-url"]
    GOOGLE_CLIENT_SECRET = google_secret_manager_secret.google_client_secret.secret_id
    VOICE_SECRETS_KEY    = google_secret_manager_secret.voice_secrets_key.secret_id
  }, local.whatsapp_external_secrets) : {}
}

resource "google_secret_manager_secret" "whatsapp" {
  for_each  = var.whatsapp_enabled ? toset(["app-secret", "verify-token"]) : toset([])
  secret_id = "${local.name}-whatsapp-${each.key}"
  labels    = local.labels

  replication {
    auto {}
  }

  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret_version" "whatsapp_app_secret" {
  count       = var.whatsapp_enabled ? 1 : 0
  secret      = google_secret_manager_secret.whatsapp["app-secret"].id
  secret_data = var.whatsapp_app_secret
}

resource "google_secret_manager_secret_version" "whatsapp_verify_token" {
  count       = var.whatsapp_enabled ? 1 : 0
  secret      = google_secret_manager_secret.whatsapp["verify-token"].id
  secret_data = var.whatsapp_verify_token
}

resource "google_service_account" "whatsapp" {
  count        = var.whatsapp_enabled ? 1 : 0
  account_id   = "${local.name}-whatsapp"
  display_name = "WhatsApp agent runtime"
}

resource "google_secret_manager_secret_iam_member" "whatsapp" {
  for_each = local.whatsapp_secrets

  secret_id = each.value
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.whatsapp[0].email}"
}

# The agent's answers come from Gemini on Vertex AI, using the service account (no API key to manage).
resource "google_project_iam_member" "whatsapp_vertex" {
  count   = var.whatsapp_enabled ? 1 : 0
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.whatsapp[0].email}"
}

module "whatsapp" {
  count  = var.whatsapp_enabled ? 1 : 0
  source = "./modules/cloud-run-service"

  name                  = "${local.name}-whatsapp"
  region                = var.region
  labels                = local.labels
  service_account_email = google_service_account.whatsapp[0].email
  vpc                   = { network = module.network.vpc_id, subnet = module.network.subnet_id }

  # Public, because Meta calls it; every request is refused unless it carries Meta's signature. Each request waits for
  # the model and for Meta, so concurrency is modest, and the instance count is capped for the small database. Scales to
  # zero while we are building; set min_instances to 1 before real patients write in, so a message never waits.
  public          = true
  min_instances   = 0
  max_instances   = 3
  concurrency     = 20
  timeout_seconds = 60
  memory          = "512Mi"

  env = merge(local.platform_env, {
    VOICE_GCP_PROJECT     = var.project_id
    KNOWLEDGE_GCP_PROJECT = var.project_id # the knowledge search embeds each question with Vertex AI (text-embedding-005)
  })
  secret_env = local.whatsapp_secrets

  depends_on = [
    google_project_service.apis,
    google_secret_manager_secret_iam_member.whatsapp,
    google_secret_manager_secret_version.google_client_secret,
    google_secret_manager_secret_version.voice_secrets_key,
    google_secret_manager_secret_version.whatsapp_app_secret,
    google_secret_manager_secret_version.whatsapp_verify_token,
  ]
}
