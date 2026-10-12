output "connection_name" {
  value = google_sql_database_instance.postgres.connection_name
}

output "private_ip" {
  value = google_sql_database_instance.postgres.private_ip_address
}

output "secret_ids" {
  description = "Secret Manager secrets: owner-url, app-password, system-password."
  value       = { for k, v in google_secret_manager_secret.db : k => v.secret_id }
}
