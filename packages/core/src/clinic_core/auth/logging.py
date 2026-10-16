import logging

logger = logging.getLogger("avishkar.auth")


def audit(event: str) -> None:
    # Deliberately never log OAuth payloads, query strings, cookies, email or exception details.
    logger.info("auth_event=%s", event)
