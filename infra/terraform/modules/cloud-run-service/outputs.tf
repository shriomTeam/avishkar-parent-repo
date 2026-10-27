output "name" {
  value = google_cloud_run_v2_service.this.name
}

output "uri" {
  description = "The address Cloud Run actually assigned."
  value       = google_cloud_run_v2_service.this.uri
}

output "cpu_idle" {
  description = "Whether the service explicitly uses request-based CPU allocation."
  value       = google_cloud_run_v2_service.this.template[0].containers[0].resources[0].cpu_idle
}
