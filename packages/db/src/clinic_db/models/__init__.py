"""Importing this package registers every table on ``Base.metadata``.

Feature teams add their tables in ``models/<feature>.py`` (Postgres schema named
after the feature, see ``clinic_db.base.FEATURE_SCHEMAS``) and import it here.
Features without tables yet: blueprints (computed from core), lead_response,
reviews, scribe, command_center, photos.
"""

from clinic_db.models import auth, core, engagement, knowledge, lead_response, membership, ops, reactivation, staging, voice

__all__ = ["auth", "core", "engagement", "knowledge", "lead_response", "membership", "ops", "reactivation", "staging", "voice"]
