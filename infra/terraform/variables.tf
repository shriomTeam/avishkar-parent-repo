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
