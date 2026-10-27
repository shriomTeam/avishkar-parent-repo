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

variable "twilio_enabled" {
  type        = bool
  default     = false
  description = "Let clinics buy phone numbers through Twilio. Turn on only after TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN are added to the production environment."
}

variable "twilio_account_sid" {
  type        = string
  default     = ""
  description = "Twilio account SID (starts with AC). Not secret; set from the TWILIO_ACCOUNT_SID repo or environment variable."

  validation {
    condition     = !var.twilio_enabled || startswith(var.twilio_account_sid, "AC")
    error_message = "twilio_enabled needs twilio_account_sid, the account SID that starts with AC. Add the TWILIO_ACCOUNT_SID variable."
  }
}

variable "twilio_auth_token" {
  type        = string
  default     = ""
  sensitive   = true
  description = "Twilio auth token. Set from the TWILIO_AUTH_TOKEN GitHub secret; Terraform stores it in Secret Manager."

  validation {
    condition     = !var.twilio_enabled || length(var.twilio_auth_token) > 0
    error_message = "twilio_enabled needs twilio_auth_token. Add the TWILIO_AUTH_TOKEN GitHub secret."
  }
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
