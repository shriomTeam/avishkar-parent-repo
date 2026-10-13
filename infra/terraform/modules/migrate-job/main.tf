resource "google_service_account" "migrate" {
  account_id   = "${var.name}-migrate"
  display_name = "Runs database migrations"
}

resource "google_secret_manager_secret_iam_member" "migrate" {
  for_each = var.secret_ids

  secret_id = each.value
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.migrate.email}"
}

resource "google_cloud_run_v2_job" "migrate" {
  name                = "${var.name}-migrate"
  location            = var.region
  labels              = var.labels
  deletion_protection = false

  template {
    template {
      service_account = google_service_account.migrate.email
      max_retries     = 0
      timeout         = "600s"

      containers {
        # Placeholder. The migrate workflow builds the real image and points the job at it.
        image = "us-docker.pkg.dev/cloudrun/container/job:latest"

        resources {
          limits = {
            cpu    = "1"
            memory = "512Mi"
          }
        }

        env {
          name = "DATABASE_OWNER_URL"
          value_source {
            secret_key_ref {
              secret  = var.secret_ids["owner-url"]
              version = "latest"
            }
          }
        }
        env {
          name = "CLINIC_APP_PASSWORD"
          value_source {
            secret_key_ref {
              secret  = var.secret_ids["app-password"]
              version = "latest"
            }
          }
        }
        env {
          name = "CLINIC_SYSTEM_PASSWORD"
          value_source {
            secret_key_ref {
              secret  = var.secret_ids["system-password"]
              version = "latest"
            }
          }
        }
      }

      # Direct VPC egress: reaches the private Cloud SQL IP with no connector to pay for.
      vpc_access {
        egress = "PRIVATE_RANGES_ONLY"

        network_interfaces {
          network    = var.network_id
          subnetwork = var.subnet_id
        }
      }
    }
  }

  lifecycle {
    ignore_changes = [template[0].template[0].containers[0].image]
  }

  depends_on = [google_secret_manager_secret_iam_member.migrate]
}
