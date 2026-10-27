"""Trusted, escaped templates. Add a factory here to reuse the email service."""

from html import escape
from importlib.resources import files
from string import Template
from urllib.parse import urlsplit

from clinic_engagement.email.types import EmailContent


def invitation(*, workspace: str, inviter: str, role: str, email: str, url: str, hours: int) -> EmailContent:
    if urlsplit(url).scheme not in {"http", "https"}:
        raise ValueError("Invitation URL must be HTTP(S)")
    values = {
        "workspace": workspace,
        "inviter": inviter,
        "role": role.replace("_", " "),
        "email": email,
        "url": url,
        "hours": str(hours),
    }
    source = files(__package__)
    return EmailContent(
        subject="You’re invited to an Avishkar AI workspace",
        text=Template(source.joinpath("invitation.txt").read_text()).substitute(values),
        html=Template(source.joinpath("invitation.html").read_text()).substitute(
            {k: escape(v, quote=True) for k, v in values.items()}
        ),
    )


def verification(code: str) -> EmailContent:
    if not code.isdigit() or len(code) != 6:
        raise ValueError("Invalid verification code")
    source = files(__package__)
    return EmailContent(
        "Verify your Avishkar AI invitation",
        Template(source.joinpath("verification.txt").read_text()).substitute(code=code),
        Template(source.joinpath("verification.html").read_text()).substitute(code=code),
    )
