data "google_project" "this" {}

locals {
  # Every resource name starts with this, e.g. "prod-avishkar-vpc".
  name = "${var.environment}-avishkar"

  labels = {
    environment = var.environment
    managed_by  = "terraform"
  }

  # Cloud Run's default addresses follow a fixed pattern, so each service's URL is known before it exists.
  # The web build needs the API's, and the API needs the web's for sign-in.
  api_host = "${local.name}-api-${data.google_project.this.number}.${var.region}.run.app"
  web_host = "${local.name}-web-${data.google_project.this.number}.${var.region}.run.app"
  api_url  = "https://${local.api_host}"

  # The private service that reads uploaded knowledge-base files. Cloud Tasks calls it at this address.
  ingest_host = "${local.name}-ingest-${data.google_project.this.number}.${var.region}.run.app"
  ingest_url  = "https://${local.ingest_host}"
  web_url     = "https://${local.web_host}"
}
