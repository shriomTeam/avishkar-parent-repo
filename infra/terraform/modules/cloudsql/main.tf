resource "google_sql_database_instance" "postgres" {
  name             = "${var.name}-postgres"
  region           = var.region
  database_version = var.db_version

  # Guards against terraform destroy and against replacement by an accidental change.
  deletion_protection = true

  settings {
    tier              = var.db_tier
    edition           = "ENTERPRISE"
    availability_type = "ZONAL"
    disk_type         = "PD_HDD"
    disk_size         = 10
    disk_autoresize   = false
    user_labels       = var.labels

    ip_configuration {
      ipv4_enabled    = false
      private_network = var.network_id
    }

    backup_configuration {
      enabled                        = true
      point_in_time_recovery_enabled = false
    }

    deletion_protection_enabled = true
  }

  # Not referenced in the config, only ordering: the VPC connection must exist first.
  depends_on = [var.private_connection_id]
}

resource "google_sql_database" "app" {
  name     = var.db_name
  instance = google_sql_database_instance.postgres.name
}

# Migrations run as clinic_owner (DATABASE_OWNER_URL). The migration job creates clinic_app and
# clinic_system and clinic_auth with the passwords below (see clinic_db.bootstrap_roles).
resource "random_password" "db" {
  for_each = toset(["owner", "app", "system", "auth"])

  length  = 32
  special = false
}

resource "google_sql_user" "owner" {
  name     = "clinic_owner"
  instance = google_sql_database_instance.postgres.name
  password = random_password.db["owner"].result
}

locals {
  secret_values = {
    "owner-url"       = "postgresql+psycopg://clinic_owner:${random_password.db["owner"].result}@${google_sql_database_instance.postgres.private_ip_address}:5432/${var.db_name}"
    "app-password"    = random_password.db["app"].result
    "system-password" = random_password.db["system"].result
    "auth-password"   = random_password.db["auth"].result
    "auth-url"        = "postgresql+psycopg://clinic_auth:${random_password.db["auth"].result}@${google_sql_database_instance.postgres.private_ip_address}:5432/${var.db_name}"
    "app-url"         = "postgresql+psycopg://clinic_app:${random_password.db["app"].result}@${google_sql_database_instance.postgres.private_ip_address}:5432/${var.db_name}"
    "system-url"      = "postgresql+psycopg://clinic_system:${random_password.db["system"].result}@${google_sql_database_instance.postgres.private_ip_address}:5432/${var.db_name}"
  }
}

resource "google_secret_manager_secret" "db" {
  for_each = toset(["owner-url", "app-password", "system-password", "auth-password", "auth-url", "app-url", "system-url"])

  secret_id = "${var.name}-db-${each.key}"
  labels    = var.labels

  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "db" {
  for_each = google_secret_manager_secret.db

  secret      = each.value.id
  secret_data = local.secret_values[each.key]
}
