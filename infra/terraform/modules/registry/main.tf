resource "google_artifact_registry_repository" "docker" {
  repository_id = "${var.name}-docker"
  location      = var.region
  format        = "DOCKER"
  labels        = var.labels

  # Old images cost storage; keep the 10 newest versions of each image.
  cleanup_policies {
    id     = "keep-latest-10"
    action = "KEEP"

    most_recent_versions {
      keep_count = 10
    }
  }

  cleanup_policies {
    id     = "delete-others"
    action = "DELETE"

    condition {
      tag_state = "ANY"
    }
  }
}
