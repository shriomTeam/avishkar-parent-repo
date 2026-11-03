"""The acknowledgement: the first answer a lead gets, within seconds, even with AI off.

Order matters and is fixed:
  1. In ONE transaction: find the text, make the priority task (one per wait) and, with it, the holding and escalation
     jobs. This commits BEFORE anything is sent, and it happens whether or not the contact has opted out, the ack is
     capped, or the send later fails: a lead whose ack failed is exactly the lead staff must see.
  2. Decide whether an ack is due at all (a staff reply, an ack already sent for this wait, a bot answering our own
     message, too many acks to this contact today). If not, the job ends here. The task already exists.
  3. Send, once. The gateway key is ``ack:{task_id}``, so however many ack jobs a wait has (every text of it writes one)
     and however often a job is run again, only one ack is ever made. A crash after the provider took the message but
     before the job was marked done runs the job again, the gateway answers "duplicate", and nothing is resent.

The wording is read from the clinic's settings when the job runs, never saved with the job, and nothing about AI is
read.
Acks ignore quiet hours and need no grant (the gateway's rule); an opted-out contact is blocked by the gateway.
"""

import logging
import uuid
from datetime import timedelta

from clinic_lead_response.engine.results import Cancel, Done, End, Wait
from clinic_lead_response.engine.tasks import (
    ensure_task,
    latest_outbound_at,
    load_inbound,
    mark_first_ack,
    schedule_timers,
    sent_since,
    staff_replied_since,
)
from clinic_lead_response.gateway.log import log_event
from clinic_lead_response.gateway.types import Lane, MessageStatus, Outcome, Purpose, SendRequest, SendResult
from clinic_lead_response.settings_store import current_settings

log = logging.getLogger("lead_response.engine")

DAILY_ACK_CAP = 3  # automatic acks to one contact in one conversation in 24 hours
AUTO_REPLY_SECONDS = 5  # a text this soon after our own message is treated as a machine answering it
DAY = timedelta(hours=24)

SENT_STATUSES = frozenset({MessageStatus.QUEUED, MessageStatus.SENT, MessageStatus.DELIVERED})


async def handle(engine, job) -> End:
    try:
        message_id = uuid.UUID(str(job.payload["message_id"]))
    except (KeyError, ValueError):
        return Cancel("bad_payload")
    trace_id = job.trace_id or uuid.uuid4()

    async with engine.scope(job.tenant_id) as session:
        inbound = await load_inbound(session, message_id)
        if inbound is None:
            return Cancel("message_missing")
        _version, settings = await current_settings(session)
        task = await ensure_task(
            session,
            conversation_id=inbound.conversation_id,
            contact_id=inbound.contact_id,
            received_at=inbound.received_at,
            trace_id=trace_id,
        )
        if task.created:
            await schedule_timers(
                session,
                task,
                conversation_id=inbound.conversation_id,
                trace_id=trace_id,
                holding_minutes=settings.holding_minutes,
                sla_minutes=settings.sla_minutes,
            )
        # The task and its timers are written. Everything below only decides whether to send.
        skip = await _reason_not_to_send(engine, session, inbound, task)
        text = settings.ack_text  # read now, at run time
    if skip is not None:
        log_event(
            log, "ack_skipped", tenant_id=job.tenant_id, trace_id=trace_id, job_id=job.id, task_id=task.id, reason=skip
        )
        return Done(skip)

    request = SendRequest(
        conversation_id=inbound.conversation_id,
        purpose=Purpose.ACK,
        body=text,
        lane=Lane.LIVE,
        idempotency_key=f"ack:{task.id}",
        trace_id=trace_id,
    )
    result = await engine.gateway.send(job.tenant_id, request)
    if result.outcome is Outcome.DUPLICATE and result.status is MessageStatus.FAILED:
        # An earlier run of this very ack failed in a way the gateway may retry: this run is the retry.
        result = await engine.gateway.attempt_again(job.tenant_id, result.message_id, lane=Lane.LIVE, trace_id=trace_id)
    end = _end_for(result, engine.now())
    if _went_out(result):
        async with engine.scope(job.tenant_id) as session:
            await mark_first_ack(session, task.id, engine.now())
    log_event(
        log,
        "ack",
        tenant_id=job.tenant_id,
        trace_id=trace_id,
        job_id=job.id,
        task_id=task.id,
        message_id=result.message_id,
        outcome=result.outcome.value,
        reason=result.reason,
    )
    return end


async def _reason_not_to_send(engine, session, inbound, task) -> str | None:
    if await staff_replied_since(session, inbound.conversation_id, task.received_at):
        return "staff_replied"
    if task.first_ack_at is not None:
        return "already_acked"
    last_out = await latest_outbound_at(session, inbound.conversation_id)
    if last_out is not None and timedelta(0) <= inbound.received_at - last_out <= timedelta(seconds=AUTO_REPLY_SECONDS):
        return "auto_reply"
    if await sent_since(session, inbound.conversation_id, "ack", engine.now() - DAY) >= DAILY_ACK_CAP:
        return "capped"
    return None


def _went_out(result: SendResult) -> bool:
    if result.outcome is Outcome.SENT:
        return True
    return result.outcome is Outcome.DUPLICATE and result.status in SENT_STATUSES


def _end_for(result: SendResult, now) -> End:
    """What each of the gateway's seven answers means for the job."""
    match result.outcome:
        case Outcome.SENT:
            return Done()
        case Outcome.DUPLICATE:
            return Done("uncertain" if result.status is MessageStatus.SENDING else "duplicate")
        case Outcome.RETRY:
            return Wait(now + timedelta(seconds=result.retry_after_seconds or 0))
        case Outcome.FAILED:
            return Done(f"failed_{result.reason}")
        case Outcome.BLOCKED:
            return Done(f"blocked_{result.reason}")
        case Outcome.DEFERRED:
            return Wait(result.until)
        case Outcome.UNCERTAIN:
            return Done("uncertain")  # never resent: a delivery receipt, or the stuck-message sweep, settles it
