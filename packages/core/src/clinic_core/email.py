"""Shared email-address validation with no identity linking or alias guessing."""

import re


def normalize_email(value: str) -> str:
    value = value.strip()
    if len(value) > 254 or not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,63}", value):
        raise ValueError("invalid_email")
    local, domain = value.rsplit("@", 1)
    if (
        len(local) > 64
        or local.startswith(".")
        or local.endswith(".")
        or ".." in local
        or any(
            not label or len(label) > 63 or label.startswith("-") or label.endswith("-") for label in domain.split(".")
        )
    ):
        raise ValueError("invalid_email")
    return (local.lower() if domain.lower() in {"gmail.com", "googlemail.com"} else local) + "@" + domain.lower()
