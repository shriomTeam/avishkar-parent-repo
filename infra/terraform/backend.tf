# Bucket and prefix are per environment: terraform init -backend-config=envs/prod.backend.hcl
terraform {
  backend "gcs" {}
}
