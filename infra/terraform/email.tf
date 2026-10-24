# Values are provisioned outside Terraform so API keys never enter tfvars or state.
resource "google_secret_manager_secret" "email" {
  for_each  = toset(["sendgrid-api-key", "email-payload-key"])
  secret_id = "${local.name}-${each.key}"
  replication {
    auto {}
  }
  labels = local.labels
}

resource "google_project_service" "email_scheduler" {
  count              = var.invitations_enabled ? 1 : 0
  service            = "cloudscheduler.googleapis.com"
  disable_on_destroy = false
}

locals {
  email_environment = {
    APP_ENV             = "production"
    INVITATIONS_ENABLED = tostring(var.invitations_enabled)
    EMAIL_PROVIDER      = "sendgrid"
    EMAIL_FROM_ADDRESS  = var.email_from_address
    EMAIL_FROM_NAME     = var.email_from_name
    EMAIL_REPLY_TO      = var.email_reply_to
  }
  email_secrets = {
    DATABASE_SYSTEM_URL          = module.cloudsql.secret_ids["system-url"]
    SENDGRID_API_KEY             = google_secret_manager_secret.email["sendgrid-api-key"].secret_id
    EMAIL_PAYLOAD_ENCRYPTION_KEY = google_secret_manager_secret.email["email-payload-key"].secret_id
  }
}

resource "google_service_account" "email_worker" {
  count        = var.invitations_enabled ? 1 : 0
  account_id   = "${local.name}-email-worker"
  display_name = "Transactional email recovery only"
}

resource "google_secret_manager_secret_iam_member" "email_worker" {
  for_each  = var.invitations_enabled ? local.email_secrets : {}
  secret_id = each.value
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.email_worker[0].email}"
}

resource "google_cloud_run_v2_job" "email" {
  count               = var.invitations_enabled ? 1 : 0
  name                = "${local.name}-email"
  location            = var.region
  deletion_protection = false
  labels              = local.labels
  template {
    template {
      service_account = google_service_account.email_worker[0].email
      timeout         = "600s"
      max_retries     = 1
      containers {
        # Release workflow replaces this placeholder with the current API image.
        image   = "us-docker.pkg.dev/cloudrun/container/job:latest"
        command = ["/app/.venv/bin/python"]
        args    = ["-m", "clinic_engagement.email.worker", "--once"]
        resources {
          limits = { cpu = "1", memory = "512Mi" }
        }
        dynamic "env" {
          for_each = local.email_environment
          content {
            name  = env.key
            value = env.value
          }
        }
        dynamic "env" {
          for_each = local.email_secrets
          content {
            name = env.key
            value_source {
              secret_key_ref {
                secret  = env.value
                version = "latest"
              }
            }
          }
        }
      }
      vpc_access {
        egress = "PRIVATE_RANGES_ONLY"
        network_interfaces {
          network    = module.network.vpc_id
          subnetwork = module.network.subnet_id
        }
      }
    }
  }
  lifecycle {
    ignore_changes = [template[0].template[0].containers[0].image, client, client_version]
  }
  depends_on = [google_secret_manager_secret_iam_member.email_worker]
}

resource "google_service_account" "email_scheduler" {
  count        = var.invitations_enabled ? 1 : 0
  account_id   = "${local.name}-email-schedule"
  display_name = "Invokes only the transactional email job"
}

resource "google_cloud_run_v2_job_iam_member" "email_scheduler" {
  count    = var.invitations_enabled ? 1 : 0
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_job.email[0].name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.email_scheduler[0].email}"
}

resource "google_cloud_scheduler_job" "email" {
  count            = var.invitations_enabled ? 1 : 0
  name             = "${local.name}-email"
  region           = var.region
  schedule         = "*/5 * * * *"
  time_zone        = "Etc/UTC"
  attempt_deadline = "60s"
  http_target {
    http_method = "POST"
    uri         = "https://run.googleapis.com/v2/projects/${var.project_id}/locations/${var.region}/jobs/${google_cloud_run_v2_job.email[0].name}:run"
    body        = base64encode("{}")
    headers     = { "Content-Type" = "application/json" }
    oauth_token {
      service_account_email = google_service_account.email_scheduler[0].email
    }
  }
  depends_on = [google_project_service.email_scheduler, google_cloud_run_v2_job_iam_member.email_scheduler]
}

# Adopt pre-existing containers without ever reading their secret values into state.
import {
  for_each = var.email_secrets_preprovisioned ? toset(["sendgrid-api-key", "email-payload-key"]) : toset([])
  to       = google_secret_manager_secret.email[each.value]
  id       = "projects/${var.project_id}/secrets/${local.name}-${each.value}"
}
