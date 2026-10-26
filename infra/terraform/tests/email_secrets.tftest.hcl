mock_provider "google" {
  override_during = plan
}
mock_provider "random" {}

variables {
  project_id           = "test-project"
  region               = "us-east1"
  environment          = "test"
  google_client_id     = "test-client"
  google_client_secret = "test-only-oauth"
}

run "enabled_credentials_and_generated_key" {
  command = plan
  variables {
    invitations_enabled = true
    email_from_address  = "sender@example.com"
    sendgrid_api_key    = "test-only-sendgrid"
  }
  override_resource {
    override_during = plan
    target          = random_bytes.email_payload_key
    values          = { base64 = "//////////////////////////////////////////8=" }
  }
  assert {
    condition     = google_secret_manager_secret_version.sendgrid_api_key[0].secret_data == var.sendgrid_api_key
    error_message = "SendGrid must use the supplied production credential."
  }
  assert {
    condition     = google_secret_manager_secret_version.email_payload_key.secret_data == "__________________________________________8="
    error_message = "The 32-byte key must become URL-safe base64 without losing padding."
  }
  assert {
    condition     = contains(keys(local.api_secrets), "EMAIL_PAYLOAD_ENCRYPTION_KEY") && contains(keys(local.email_secrets), "SENDGRID_API_KEY")
    error_message = "Both API and sender/recovery must receive email secrets."
  }
  assert {
    condition     = !contains(keys(local.api_secrets), "EMAIL_OLD_PAYLOAD_KEYS")
    error_message = "Old keys must not be injected unless explicitly enabled."
  }
}

run "missing_sendgrid_rejected" {
  command = plan
  variables {
    invitations_enabled = true
    email_from_address  = "sender@example.com"
    sendgrid_api_key    = ""
  }
  expect_failures = [var.sendgrid_api_key]
}

run "old_key_compatibility" {
  command = plan
  variables {
    invitations_enabled            = true
    email_from_address             = "sender@example.com"
    sendgrid_api_key               = "test-only-sendgrid"
    email_old_payload_keys_enabled = true
    email_old_payload_keys         = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
  }
  assert {
    condition     = google_secret_manager_secret_version.email_old_payload_keys[0].secret_data == var.email_old_payload_keys
    error_message = "Old ciphertext keys must be retained in a managed secret version."
  }
  assert {
    condition     = local.api_secrets["EMAIL_OLD_PAYLOAD_KEYS"] == local.email_secrets["EMAIL_OLD_PAYLOAD_KEYS"]
    error_message = "The API and sender/recovery must use the same compatibility secret."
  }
}

run "invalid_old_keys_rejected" {
  command = plan
  variables {
    email_old_payload_keys_enabled = true
    email_old_payload_keys         = "invalid-key"
  }
  expect_failures = [var.email_old_payload_keys]
}

run "disabled_invitations_need_no_sendgrid" {
  command = plan
  assert {
    condition     = length(google_secret_manager_secret_version.sendgrid_api_key) == 0 && !contains(keys(local.api_secrets), "SENDGRID_API_KEY")
    error_message = "Disabled invitations must not require or inject SendGrid."
  }
}

run "recovery_reuses_sender_service" {
  command = plan
  override_resource {
    target          = google_service_account.email_scheduler[0]
    override_during = plan
    values          = { email = "scheduler@test-project.iam.gserviceaccount.com" }
  }
  variables {
    invitations_enabled = true
    email_from_address  = "sender@example.com"
    sendgrid_api_key    = "test-only-sendgrid"
  }
  assert {
    condition     = google_cloud_scheduler_job.email[0].schedule == "*/30 * * * *" && google_cloud_scheduler_job.email[0].http_target[0].uri == "${local.email_send_url}/tasks/email/reconcile"
    error_message = "Recovery must use the existing email service every 30 minutes."
  }
  assert {
    condition     = google_cloud_scheduler_job.email[0].http_target[0].oidc_token[0].audience == local.email_send_url
    error_message = "Recovery OIDC tokens must target the email service audience."
  }
  assert {
    condition     = local.email_environment["EMAIL_RECOVERY_INVOKER_EMAIL"] == google_service_account.email_scheduler[0].email
    error_message = "The handler must receive the dedicated Scheduler identity."
  }
}
