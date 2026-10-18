variable "project_id" {
  type        = string
  description = "GCP project that holds all resources."
}

variable "region" {
  type        = string
  description = "Region for the subnet and the database."
}

variable "environment" {
  type        = string
  description = "Environment name. It prefixes every resource name and is set as a label."
}

variable "db_tier" {
  type        = string
  description = "Cloud SQL machine tier. db-f1-micro is the cheapest."
  default     = "db-f1-micro"
}

variable "db_version" {
  type        = string
  description = "Cloud SQL Postgres version. Local dev runs Postgres 17."
  default     = "POSTGRES_17"
}

variable "db_name" {
  type        = string
  description = "Application database. The app and Alembic migrations expect \"clinic\"."
  default     = "clinic"
}

variable "google_client_id" {
  type        = string
  description = "Google OAuth client ID for sign-in. Not secret (it is in the sign-in URL); set from the GOOGLE_CLIENT_ID repo variable."
}

variable "google_client_secret" {
  type        = string
  sensitive   = true
  description = "Google OAuth client secret. Set from the GOOGLE_CLIENT_SECRET GitHub secret; Terraform stores it in Secret Manager."

  validation {
    condition     = length(var.google_client_secret) > 0
    error_message = "google_client_secret is empty. Add the GOOGLE_CLIENT_SECRET GitHub secret."
  }
}
