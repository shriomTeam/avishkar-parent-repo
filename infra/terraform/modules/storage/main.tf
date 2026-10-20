# Private file storage for the platform. Features keep their files under their own folder (prefix),
# e.g. voice recordings go in "recordings/". The bucket holds patient audio, so nothing here is public.
resource "google_storage_bucket" "files" {
  # Bucket names are global, so the project id keeps this one unique.
  name     = "${var.name}-${var.project_id}-files"
  location = var.region
  labels   = var.labels

  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"

  # Terraform will not delete a bucket that still holds files.
  force_destroy = false
}

# The API can create, read and delete files. It cannot list or change buckets.
resource "google_storage_bucket_iam_member" "writer" {
  bucket = google_storage_bucket.files.name
  role   = "roles/storage.objectUser"
  member = "serviceAccount:${var.writer_service_account_email}"
}
