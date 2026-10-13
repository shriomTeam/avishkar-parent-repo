locals {
  # Every resource name starts with this, e.g. "prod-avishkar-vpc".
  name = "${var.environment}-avishkar"

  labels = {
    environment = var.environment
    managed_by  = "terraform"
  }
}
