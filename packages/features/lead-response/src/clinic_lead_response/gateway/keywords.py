"""What an inbound text means to the carriers: STOP, START or HELP.

The lists are the ones Twilio documents as its defaults for opt-out and opt-in (checked 2026-10-30). The match is exact
after trimming and case folding, never a substring, so "please stop" and "STOP." are ordinary messages here (whether
to also accept trailing punctuation for STOP is a question for Shriom).
"""

from enum import StrEnum


class Keyword(StrEnum):
    STOP = "stop"
    START = "start"
    HELP = "help"


STOP_KEYWORDS = frozenset({"stop", "unsubscribe", "end", "quit", "stopall", "revoke", "optout", "cancel"})
START_KEYWORDS = frozenset({"start", "unstop", "yes"})
HELP_KEYWORDS = frozenset({"help"})


def classify_inbound(text: str) -> Keyword | None:
    word = text.strip().casefold()
    if word in STOP_KEYWORDS:
        return Keyword.STOP
    if word in START_KEYWORDS:
        return Keyword.START
    if word in HELP_KEYWORDS:
        return Keyword.HELP
    return None
