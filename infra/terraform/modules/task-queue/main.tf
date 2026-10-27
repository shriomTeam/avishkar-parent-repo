# A Cloud Tasks queue that calls an HTTP service and retries until it answers 2xx. Rate limits protect the small
# database: only a few calls run at once, however many files are uploaded together.
resource "google_cloud_tasks_queue" "this" {
  name     = var.name
  location = var.region

  rate_limits {
    max_dispatches_per_second = var.max_dispatches_per_second
    max_concurrent_dispatches = var.max_concurrent_dispatches
  }

  retry_config {
    max_attempts  = var.max_attempts
    min_backoff   = "10s"
    max_backoff   = "300s"
    max_doublings = 4
  }
}
