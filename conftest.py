"""Routine repository tests must never inherit live email credentials from .env."""

import os

# Set before app/settings modules are collected. Provider unit tests inject their
# own fake key and HTTP transport explicitly.
os.environ["EMAIL_PROVIDER"] = "test"
os.environ["INVITATIONS_ENABLED"] = "false"
os.environ["SENDGRID_API_KEY"] = ""
