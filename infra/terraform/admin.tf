# The admin console runs as its own public Cloud Run service, apart from the API and the web app. It has one operator
# login. Terraform generates the user name's password and the cookie signing key and keeps them in Secret Manager, so
# no person ever has to choose or paste them. The console reads the clinic database as `clinic_system`, the role that
# bypasses row-level security, and writes an audit line for every change it makes. Off until `admin_enabled` is true.
#
# Read the sign-in details (do this from a trusted machine, and do not paste them anywhere):
#   gcloud secrets versions access latest --secret=<name>-admin-username
#   gcloud secrets versions access latest --secret=<name>-admin-password
# To change the password, taint the random_password.admin resource and apply, then deploy again (secrets are read when
# an instance starts). Changing the session key signs every operator out.

locals {
  admin_host = "${local.name}-admin-${data.google_project.this.number}.${var.region}.run.app"
  admin_url  = "https://${local.admin_host}"

  admin_secret_names = var.admin_enabled ? toset(["username", "password", "session-key"]) : toset([])

  # DATABASE_SYSTEM_URL is the existing clinic_system connection. GOOGLE_CLIENT_SECRET is only there because the shared
  # production settings check (loaded when features are listed) demands it.
  admin_secrets = var.admin_enabled ? {
    ADMIN_USERNAME       = google_secret_manager_secret.admin["username"].secret_id
    ADMIN_PASSWORD       = google_secret_manager_secret.admin["password"].secret_id
    ADMIN_SESSION_KEY    = google_secret_manager_secret.admin["session-key"].secret_id
    DATABASE_SYSTEM_URL  = module.cloudsql.secret_ids["system-url"]
    GOOGLE_CLIENT_SECRET = google_secret_manager_secret.google_client_secret.secret_id
  } : {}
}

resource "random_password" "admin" {
  for_each = var.admin_enabled ? toset(["password", "session-key"]) : toset([])
  length   = each.key == "password" ? 32 : 64
  special  = false
}

resource "google_secret_manager_secret" "admin" {
  for_each  = local.admin_secret_names
  secret_id = "${local.name}-admin-${each.key}"
  labels    = local.labels

  replication {
    auto {}
  }

  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret_version" "admin" {
  for_each    = local.admin_secret_names
  secret      = google_secret_manager_secret.admin[each.key].id
  secret_data = each.key == "username" ? var.admin_username : random_password.admin[each.key].result
}

resource "google_service_account" "admin" {
  count        = var.admin_enabled ? 1 : 0
  account_id   = "${local.name}-admin"
  display_name = "Admin console runtime"
}

resource "google_secret_manager_secret_iam_member" "admin" {
  for_each = local.admin_secrets

  secret_id = each.value
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.admin[0].email}"
}

module "admin" {
  count  = var.admin_enabled ? 1 : 0
  source = "./modules/cloud-run-service"

  name                  = "${local.name}-admin"
  region                = var.region
  labels                = local.labels
  service_account_email = google_service_account.admin[0].email
  vpc                   = { network = module.network.vpc_id, subnet = module.network.subnet_id }

  # Public, because operators reach it from anywhere; every page except /login and /health needs the session. One
  # instance at most: the failed-login counter lives in memory, so a second instance would double the allowed tries.
  public          = true
  min_instances   = 0
  max_instances   = 1
  concurrency     = 20
  timeout_seconds = 60
  memory          = "512Mi"

  env = merge(local.platform_env, {
    ADMIN_APP_ENV            = "production"
    ADMIN_COOKIE_SECURE      = "true"
    ADMIN_TRUSTED_PROXY_HOPS = "1" # Cloud Run's front end is the one proxy
  })
  secret_env = local.admin_secrets

  depends_on = [
    google_project_service.apis,
    google_secret_manager_secret_iam_member.admin,
    google_secret_manager_secret_version.admin,
    google_secret_manager_secret_version.google_client_secret,
  ]
}
