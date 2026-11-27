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

# Phone numbers through Twilio. Turn on after adding TWILIO_ACCOUNT_SID (variable) and TWILIO_AUTH_TOKEN (secret)
# to the GitHub environment "production".
twilio_enabled = true

# The WhatsApp agent as its own Cloud Run service. It needs WHATSAPP_APP_SECRET and WHATSAPP_VERIFY_TOKEN (secrets)
# in the GitHub environment "production"; the Terraform plan fails without them.
whatsapp_enabled = true

# The admin console as its own Cloud Run service. Terraform generates the password and session key in Secret Manager,
# so nothing needs adding to GitHub first. Set to true to create it; see admin.tf for how to read the sign-in details.
admin_enabled = true
