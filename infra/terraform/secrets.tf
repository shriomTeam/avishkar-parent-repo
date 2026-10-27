# Secrets the apps need that Terraform does not generate itself. The values come from GitHub secrets (as
# TF_VAR_*), are stored in Secret Manager, and Cloud Run reads them from there; they are never in the repo.

resource "google_secret_manager_secret" "google_client_secret" {
  secret_id = "${local.name}-google-client-secret"
  labels    = local.labels

  replication {
    auto {}
  }

  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret_version" "google_client_secret" {
  secret      = google_secret_manager_secret.google_client_secret.id
  secret_data = var.google_client_secret
}

# Encrypts custom-tool auth headers at rest. Generated here, so no one ever handles it. Changing it would make
# already-stored tool secrets unreadable, so treat it as permanent.
resource "random_bytes" "voice_secrets_key" {
  length = 32
}

resource "google_secret_manager_secret" "voice_secrets_key" {
  secret_id = "${local.name}-voice-secrets-key"
  labels    = local.labels

  replication {
    auto {}
  }

  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret_version" "voice_secrets_key" {
  secret = google_secret_manager_secret.voice_secrets_key.id
  # A Fernet key is 32 random bytes in URL-safe base64.
  secret_data = replace(replace(random_bytes.voice_secrets_key.base64, "+", "-"), "/", "_")
}

# The Twilio auth token, only when phone numbers are turned on. Like the Google secret, the value comes from a GitHub
# secret and is never in the repo.
resource "google_secret_manager_secret" "twilio_auth_token" {
  count     = var.twilio_enabled ? 1 : 0
  secret_id = "${local.name}-twilio-auth-token"
  labels    = local.labels

  replication {
    auto {}
  }

  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret_version" "twilio_auth_token" {
  count       = var.twilio_enabled ? 1 : 0
  secret      = google_secret_manager_secret.twilio_auth_token[0].id
  secret_data = var.twilio_auth_token
}
