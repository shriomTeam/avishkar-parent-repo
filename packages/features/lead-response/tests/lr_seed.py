"""One row in every lead_response table for a tenant."""

import uuid
from datetime import UTC, datetime

from clinic_core.database import tenant_session
from clinic_db.models.lead_response import (
    ConsentRecord,
    Contact,
    ContactIdentity,
    Conversation,
    Job,
    Message,
    MessageEvent,
    PracticeSettings,
    Task,
)

PHONE = "+14155550123"

# Children before parents.
TABLES = [
    "jobs",
    "message_events",
    "consent_records",
    "tasks",
    "messages",
    "conversations",
    "contact_identities",
    "contacts",
    "practice_settings",
]


async def seed(tenant: uuid.UUID, *, phone: str = PHONE) -> dict[str, uuid.UUID]:
    ids = {name: uuid.uuid4() for name in ("contact", "conversation", "message", "task")}
    async with tenant_session(tenant) as s:
        s.add(Contact(id=ids["contact"], tenant_id=tenant))
        await s.flush()
        s.add(ContactIdentity(tenant_id=tenant, contact_id=ids["contact"], kind="phone", value=phone))
        s.add(
            Conversation(
                id=ids["conversation"],
                tenant_id=tenant,
                contact_id=ids["contact"],
                channel="sms",
                channel_address="+14155550100",
            )
        )
        await s.flush()
        s.add(
            Message(
                id=ids["message"],
                tenant_id=tenant,
                conversation_id=ids["conversation"],
                direction="inbound",
                channel="sms",
                sender_kind="contact",
                body="test body",
                provider_message_id=f"SM{ids['message']}",
            )
        )
        s.add(
            Task(
                id=ids["task"],
                tenant_id=tenant,
                conversation_id=ids["conversation"],
                contact_id=ids["contact"],
                received_at=datetime.now(UTC),
            )
        )
        await s.flush()
        s.add(MessageEvent(tenant_id=tenant, message_id=ids["message"], status="queued"))
        s.add(
            ConsentRecord(
                tenant_id=tenant, contact_id=ids["contact"], channel="sms", granted=True, source="first_inbound"
            )
        )
        s.add(
            Job(
                tenant_id=tenant,
                kind="holding_message",
                run_at=datetime.now(UTC),
                idempotency_key=f"holding:{ids['task']}",
                conversation_id=ids["conversation"],
                task_id=ids["task"],
            )
        )
        s.add(PracticeSettings(tenant_id=tenant, version=1))
    return ids
