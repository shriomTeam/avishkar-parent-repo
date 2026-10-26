# External credentials follow GitHub production secrets -> TF_VAR_* -> Secret Manager versions.
# Secret values are sensitive in plans but are present in the protected Terraform state.
resource "google_secret_manager_secret" "email" {
  for_each  = toset(["sendgrid-api-key", "email-payload-key"])
  secret_id = "${local.name}-${each.key}"
  replication {
    auto {}
  }
  labels     = local.labels
  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret_version" "sendgrid_api_key" {
  count       = var.invitations_enabled ? 1 : 0
  secret      = google_secret_manager_secret.email["sendgrid-api-key"].id
  secret_data = var.sendgrid_api_key
}

# Permanent encryption identity: do not taint/replace it while encrypted mail exists.
resource "random_bytes" "email_payload_key" {
  length = 32
  lifecycle {
    prevent_destroy = true
  }
}

resource "google_secret_manager_secret_version" "email_payload_key" {
  secret      = google_secret_manager_secret.email["email-payload-key"].id
  secret_data = replace(replace(random_bytes.email_payload_key.base64, "+", "-"), "/", "_")
}

# Enable before adopting/replacing a key if queued ciphertext uses an older key.
resource "google_secret_manager_secret" "email_old_payload_keys" {
  count     = var.email_old_payload_keys_enabled ? 1 : 0
  secret_id = "${local.name}-email-old-payload-keys"
  labels    = local.labels
  replication {
    auto {}
  }
  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret_version" "email_old_payload_keys" {
  count       = var.email_old_payload_keys_enabled ? 1 : 0
  secret      = google_secret_manager_secret.email_old_payload_keys[0].id
  secret_data = var.email_old_payload_keys
}

resource "google_project_service" "email_scheduler" {
  count              = var.invitations_enabled ? 1 : 0
  service            = "cloudscheduler.googleapis.com"
  disable_on_destroy = false
}

locals {
  email_send_url = "https://${local.name}-email-send-${data.google_project.this.number}.${var.region}.run.app"
  email_task_environment = var.invitations_enabled ? {
    EMAIL_TASKS_PROJECT       = var.project_id
    EMAIL_TASKS_REGION        = var.region
    EMAIL_TASKS_QUEUE         = module.email_queue[0].name
    EMAIL_TASKS_URL           = local.email_send_url
    EMAIL_TASKS_AUDIENCE      = local.email_send_url
    EMAIL_TASKS_INVOKER_EMAIL = google_service_account.email_tasks[0].email
  } : {}
  email_environment = merge({
    APP_ENV             = "production"
    INVITATIONS_ENABLED = tostring(var.invitations_enabled)
    EMAIL_PROVIDER      = "sendgrid"
    EMAIL_FROM_ADDRESS  = var.email_from_address
    EMAIL_FROM_NAME     = var.email_from_name
    EMAIL_REPLY_TO      = var.email_reply_to
  }, local.email_task_environment)
  email_rotation_secrets = var.email_old_payload_keys_enabled ? {
    EMAIL_OLD_PAYLOAD_KEYS = google_secret_manager_secret.email_old_payload_keys[0].secret_id
  } : {}
  email_secrets = merge({
    DATABASE_SYSTEM_URL          = module.cloudsql.secret_ids["system-url"]
    SENDGRID_API_KEY             = google_secret_manager_secret.email["sendgrid-api-key"].secret_id
    EMAIL_PAYLOAD_ENCRYPTION_KEY = google_secret_manager_secret.email["email-payload-key"].secret_id
  }, local.email_rotation_secrets)
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

# Same queue/private-HTTP pattern as Knowledge Base, with its own identities and limits.
module "email_queue" {
  count                     = var.invitations_enabled ? 1 : 0
  source                    = "./modules/task-queue"
  name                      = "${local.name}-email"
  region                    = var.region
  max_dispatches_per_second = 2
  max_concurrent_dispatches = 1
  max_attempts              = 100
  depends_on                = [google_project_service.apis]
}

resource "google_service_account" "email_tasks" {
  count        = var.invitations_enabled ? 1 : 0
  account_id   = "${local.name}-email-tasks"
  display_name = "Invokes only the private email sender"
}

module "email_sender" {
  count                 = var.invitations_enabled ? 1 : 0
  source                = "./modules/cloud-run-service"
  name                  = "${local.name}-email-send"
  region                = var.region
  labels                = local.labels
  service_account_email = google_service_account.email_worker[0].email
  vpc                   = { network = module.network.vpc_id, subnet = module.network.subnet_id }
  public                = false
  min_instances         = 0
  max_instances         = 2
  concurrency           = 1
  timeout_seconds       = 60
  memory                = "512Mi"
  env                   = local.email_environment
  secret_env            = local.email_secrets
  depends_on = [
    google_secret_manager_secret_iam_member.email_worker,
    google_secret_manager_secret_version.sendgrid_api_key,
    google_secret_manager_secret_version.email_payload_key,
    google_secret_manager_secret_version.email_old_payload_keys,
  ]
}

resource "google_cloud_run_v2_service_iam_member" "email_tasks_invoke" {
  count    = var.invitations_enabled ? 1 : 0
  name     = module.email_sender[0].name
  location = var.region
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.email_tasks[0].email}"
}

# The API and recovery runner may enqueue only on this queue and impersonate only this caller.
resource "google_cloud_tasks_queue_iam_member" "email_enqueue" {
  for_each = var.invitations_enabled ? { api = google_service_account.api.email, recovery = google_service_account.email_worker[0].email } : {}
  name     = module.email_queue[0].name
  location = var.region
  role     = "roles/cloudtasks.enqueuer"
  member   = "serviceAccount:${each.value}"
}

resource "google_service_account_iam_member" "email_enqueue_caller" {
  for_each           = var.invitations_enabled ? { api = google_service_account.api.email, recovery = google_service_account.email_worker[0].email } : {}
  service_account_id = google_service_account.email_tasks[0].name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${each.value}"
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
  depends_on = [
    google_secret_manager_secret_iam_member.email_worker,
    google_cloud_tasks_queue_iam_member.email_enqueue,
    google_service_account_iam_member.email_enqueue_caller,
    google_secret_manager_secret_version.sendgrid_api_key,
    google_secret_manager_secret_version.email_payload_key,
    google_secret_manager_secret_version.email_old_payload_keys,
  ]
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

# Adopt existing containers only; Terraform creates/manages their secret versions above.
import {
  for_each = var.email_secrets_preprovisioned ? toset(["sendgrid-api-key", "email-payload-key"]) : toset([])
  to       = google_secret_manager_secret.email[each.value]
  id       = "projects/${var.project_id}/secrets/${local.name}-${each.value}"
}
