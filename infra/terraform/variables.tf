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

variable "invitations_enabled" {
  type        = bool
  default     = false
  description = "Enable after configuring the production SENDGRID_API_KEY GitHub secret and verifying the sender."
}
variable "email_from_address" {
  type        = string
  default     = ""
  description = "SendGrid-verified From address."
  validation {
    condition     = !var.invitations_enabled || length(var.email_from_address) > 0
    error_message = "An enabled invitation service requires email_from_address."
  }
}
variable "email_from_name" {
  type    = string
  default = "Avishkar AI"
}
variable "email_reply_to" {
  type    = string
  default = ""
}

variable "email_secrets_preprovisioned" {
  type        = bool
  default     = false
  description = "Import only the two existing email secret containers; Terraform manages their versions."
}

variable "sendgrid_api_key" {
  type        = string
  sensitive   = true
  default     = ""
  description = "SendGrid Mail Send credential from the production GitHub SENDGRID_API_KEY secret."
  validation {
    condition     = !var.invitations_enabled || length(trimspace(var.sendgrid_api_key)) > 0
    error_message = "Invitations require the production GitHub SENDGRID_API_KEY secret."
  }
}

variable "email_old_payload_keys_enabled" {
  type        = bool
  default     = false
  description = "Inject previous Fernet keys before adopting/rotating the generated payload key."
}

variable "email_old_payload_keys" {
  type        = string
  sensitive   = true
  default     = ""
  description = "Comma-separated previous Fernet keys from production GitHub EMAIL_OLD_PAYLOAD_KEYS; retain until old ciphertext is drained."
  validation {
    condition = !var.email_old_payload_keys_enabled || alltrue([
      for key in split(",", var.email_old_payload_keys) : can(regex("^[A-Za-z0-9_-]{43}=$", key))
    ])
    error_message = "Enabled email key compatibility requires comma-separated, 44-character URL-safe base64 Fernet keys (no spaces)."
  }
}
