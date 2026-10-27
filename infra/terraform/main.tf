# APIs that Terraform itself needs. serviceusage and cloudresourcemanager are enabled by hand
# during bootstrap, because Terraform cannot enable the API it uses to enable APIs.
resource "google_project_service" "apis" {
  for_each = toset([
    "compute.googleapis.com",
    "servicenetworking.googleapis.com",
    "sqladmin.googleapis.com",
    "secretmanager.googleapis.com",
    "run.googleapis.com",
    "artifactregistry.googleapis.com",
    "aiplatform.googleapis.com", # Vertex AI: the Gemini Live model behind voice agents
    "storage.googleapis.com",
    "cloudtasks.googleapis.com", # knowledge-base ingestion jobs
  ])

  service            = each.key
  disable_on_destroy = false
}

module "network" {
  source = "./modules/network"

  name   = local.name
  region = var.region

  depends_on = [google_project_service.apis]
}

module "cloudsql" {
  source = "./modules/cloudsql"

  name       = local.name
  region     = var.region
  labels     = local.labels
  network_id = module.network.vpc_id
  db_tier    = var.db_tier
  db_version = var.db_version
  db_name    = var.db_name

  # The private services connection must exist before an instance can use the VPC.
  private_connection_id = module.network.private_connection_id

  depends_on = [google_project_service.apis]
}

module "registry" {
  source = "./modules/registry"

  name   = local.name
  region = var.region
  labels = local.labels

  depends_on = [google_project_service.apis]
}

module "migrate_job" {
  source = "./modules/migrate-job"

  name       = local.name
  region     = var.region
  labels     = local.labels
  network_id = module.network.vpc_id
  subnet_id  = module.network.subnet_id
  secret_ids = module.cloudsql.secret_ids

  depends_on = [google_project_service.apis]
}

module "knowledge_queue" {
  source = "./modules/task-queue"

  name   = "${local.name}-knowledge-ingest"
  region = var.region

  depends_on = [google_project_service.apis]
}

module "storage" {
  source = "./modules/storage"

  name                         = local.name
  project_id                   = var.project_id
  region                       = var.region
  labels                       = local.labels
  writer_service_account_email = google_service_account.api.email

  depends_on = [google_project_service.apis]
}
