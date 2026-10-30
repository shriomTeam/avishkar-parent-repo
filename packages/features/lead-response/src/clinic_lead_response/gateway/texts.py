"""Fixed texts the gateway sends on its own."""

# PLACEHOLDER: awaiting the practice's and Shriom's wording. A carrier-compliant HELP answer names the sender and
# says how to reach a person and how to stop. The practice setting that could hold this wording does not exist yet.
HELP_TEXT_PLACEHOLDER = "{name}: for help, call our office. Reply STOP to opt out."


def help_text(practice_name: str) -> str:
    return HELP_TEXT_PLACEHOLDER.format(name=practice_name.strip() or "Our practice")
