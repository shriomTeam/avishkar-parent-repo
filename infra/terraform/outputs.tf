output "vpc_name" {
  value = module.network.vpc_name
}

output "db_instance_connection_name" {
  description = "Used by the Cloud SQL Auth Proxy and Cloud Run."
  value       = module.cloudsql.connection_name
}

output "db_private_ip" {
  value = module.cloudsql.private_ip
}

output "registry_url" {
  description = "Docker repository for images, e.g. <this>/migrate:<tag>."
  value       = module.registry.url
}

output "migrate_job_name" {
  value = module.migrate_job.name
}

output "web_url" {
  description = "Where users open the app."
  value       = local.web_url
}

output "api_url" {
  value = local.api_url
}

output "google_oauth_redirect_uri" {
  description = "Add this as an authorized redirect URI on the Google OAuth client."
  value       = "${local.web_url}/api/v1/auth/google/callback"
}

output "ingest_url" {
  description = "Private knowledge-base ingestion service. Only the Cloud Tasks queue's service account can call it."
  value       = local.ingest_url
}

output "whatsapp_webhook_url" {
  description = "Paste this into Meta's WhatsApp webhook settings. Empty until whatsapp_enabled is true."
  value       = var.whatsapp_enabled ? "${local.whatsapp_url}/whatsapp/webhook" : ""
}

output "knowledge_queue" {
  value = module.knowledge_queue.name
}

output "files_bucket" {
  description = "Private bucket for feature files; voice recordings go under voice-recordings/."
  value       = module.storage.name
}

output "admin_url" {
  description = "Address of the admin console. Empty until admin_enabled is true."
  value       = var.admin_enabled ? local.admin_url : ""
}
