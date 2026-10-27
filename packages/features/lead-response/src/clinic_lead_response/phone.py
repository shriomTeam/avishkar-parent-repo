"""Phone numbers as E.164. Pure: no library, no I/O.

Same rules as the CSV importer's ``phone_e164``: a ``+`` number with 8 to 15 digits is kept, ten digits get the default
country code, eleven digits that start with it are accepted. The database checks the result with the same pattern.
"""

import re

E164 = re.compile(r"^\+[1-9][0-9]{7,14}$")


class InvalidPhone(ValueError):
    """The message never contains the number itself, so it is safe to log."""


def normalise_phone(value: str, country_code: str = "1") -> str:
    text = value.strip()
    digits = re.sub(r"\D", "", text)
    if text.startswith("+") and 8 <= len(digits) <= 15:
        result = "+" + digits
    elif len(digits) == 10:
        result = f"+{country_code}{digits}"
    elif len(digits) == 11 and digits.startswith(country_code):
        result = "+" + digits
    else:
        raise InvalidPhone("not a recognised phone number")
    if not E164.match(result):
        raise InvalidPhone("not a recognised phone number")
    return result
