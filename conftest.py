"""Routine repository tests must never inherit live email credentials from .env."""

import os

# Set before app/settings modules are collected. Provider unit tests inject their
# own fake key and HTTP transport explicitly.
os.environ["EMAIL_PROVIDER"] = "test"
os.environ["INVITATIONS_ENABLED"] = "false"
os.environ["SENDGRID_API_KEY"] = ""

# Local tool demos must never disable SSRF checks in routine tests.
os.environ["VOICE_TOOL_ALLOW_PRIVATE_HOSTS"] = "false"

# A local .env must never cause routine tests to publish real Google Cloud Tasks.
for name in (
    "EMAIL_TASKS_PROJECT",
    "EMAIL_TASKS_REGION",
    "EMAIL_TASKS_QUEUE",
    "EMAIL_TASKS_URL",
    "EMAIL_TASKS_AUDIENCE",
    "EMAIL_TASKS_INVOKER_EMAIL",
):
    os.environ[name] = ""
