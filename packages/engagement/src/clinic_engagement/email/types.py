from dataclasses import dataclass


@dataclass(frozen=True)
class EmailContent:
    subject: str
    text: str
    html: str
