output "name" {
  value = google_cloud_run_v2_service.this.name
}

output "uri" {
  description = "The address Cloud Run actually assigned."
  value       = google_cloud_run_v2_service.this.uri
}
