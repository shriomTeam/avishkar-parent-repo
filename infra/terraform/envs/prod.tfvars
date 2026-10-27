project_id  = "avishkar-market-intelligence"
region      = "us-east1"
environment = "prod"

# Email containers already exist; Terraform imports them and manages versions.
# SENDGRID_API_KEY comes from the GitHub production environment.
# Retain the previously provisioned key during adoption. Add its value to the
# GitHub production EMAIL_OLD_PAYLOAD_KEYS secret before Plan/Apply.
invitations_enabled            = true
email_from_address             = "abhinav.chaudhary@avishkar.app"
email_from_name                = "Avishkar AI"
email_reply_to                 = "abhinav.chaudhary@avishkar.app"
email_secrets_preprovisioned   = true
email_old_payload_keys_enabled = true
