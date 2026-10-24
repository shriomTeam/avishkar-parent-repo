output "name" {
  description = "The queue's short name (the API builds the full path from the project and region)."
  value       = google_cloud_tasks_queue.this.name
}
