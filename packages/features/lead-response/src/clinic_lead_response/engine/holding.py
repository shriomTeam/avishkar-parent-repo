"""The holding message: one short text, once per wait, if nobody has answered the lead after the holding timer.

It is due ``holding_minutes`` after the text that began the wait, and that number is read from the clinic's settings
when the job FIRES, not when it was made. If the clinic has since lengthened the timer, the job puts itself back to the
new time (without counting that as a failed attempt). A shortened timer reaches only waits that begin afterwards: the
job of a wait already open was timed when the task was made and fires then. A second text from the lead during the wait
does not restart or extend anything: the job and its due time belong to the task, and the task is the same.

Before it sends, the job asks whether the message is still wanted (see ``contract.py``): the task must still be open, no
staff member may have answered, and the contact must not have opted out. If any of those is false the pending holding
and escalation jobs of the task are cancelled (``staff_reply``, ``handled``, ``task_closed`` or ``stop``). The check is
made twice: in the transaction that decides, and again in its own short transaction immediately before the gateway is
called. What remains is a window of milliseconds between that second look and the gateway writing the message, and the
provider call itself: a staff reply that lands inside it still sees the holding message go out. That cannot be closed
without holding a database lock across a network call, and it is harmless (the lead gets one neutral line).

The message is sent through the gateway as a reply (``Purpose.HOLDING``): no quiet hours, no grant needed; an opted-out
contact is blocked there as well. The gateway key ``holding:{task_id}`` makes it once per wait however often the job
runs, and at most ``DAILY_HOLDING_CAP`` holding messages go to one conversation in 24 hours.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import timedelta

from clinic_lead_response.engine.ack import DAY, _end_for, _went_out
from clinic_lead_response.engine.results import Cancel, Done, End, Wait
from clinic_lead_response.engine.tasks import sent_since
from clinic_lead_response.engine.waits import (
    TaskView,
    load_wait,
    mark_holding_sent,
    reason_to_stop,
)
from clinic_lead_response.gateway.log import log_event
from clinic_lead_response.gateway.types import Lane, MessageStatus, Outcome, Purpose, SendRequest
from clinic_lead_response.settings_store import current_settings

log = logging.getLogger("lead_response.engine")

# PLACEHOLDER. Not approved wording. It promises no time, names nobody, has no link and no personal data. It also does
# not name the clinic, and US carrier rules may expect a business to be identifiable in its messages, so the final
# wording MUST be approved (by Shriom, and the clinic's compliance) BEFORE LEAD_RESPONSE_ENGINE_ENABLED is turned on
# anywhere real.
HOLDING_TEXT_PLACEHOLDER = "Thank you for your patience. Our team has your message."

DAILY_HOLDING_CAP = 2  # holding messages to one conversation in 24 hours


@dataclass(frozen=True)
class Plan:
    task: TaskView


async def handle(engine, job) -> End:
    try:
        task_id = job.task_id or uuid.UUID(str(job.payload["task_id"]))
    except (KeyError, ValueError):
        return Cancel("bad_payload")
    trace_id = job.trace_id or uuid.uuid4()

    plan = await _look(engine, job, task_id)
    if isinstance(plan, Cancel | Done | Wait):
        return plan
    again = await _recheck(engine, job, plan)  # the last look before the gateway
    if again is not None:
        return again

    request = SendRequest(
        conversation_id=plan.task.conversation_id,
        purpose=Purpose.HOLDING,
        body=HOLDING_TEXT_PLACEHOLDER,
        lane=Lane.LIVE,
        idempotency_key=f"holding:{task_id}",
        trace_id=trace_id,
    )
    result = await engine.gateway.send(job.tenant_id, request)
    if result.outcome is Outcome.DUPLICATE and result.status is MessageStatus.FAILED:
        result = await engine.gateway.attempt_again(job.tenant_id, result.message_id, lane=Lane.LIVE, trace_id=trace_id)
    if _went_out(result):
        async with engine.scope(job.tenant_id) as session:
            await mark_holding_sent(session, task_id, engine.now())
    log_event(
        log,
        "holding",
        tenant_id=job.tenant_id,
        trace_id=trace_id,
        job_id=job.id,
        task_id=task_id,
        message_id=result.message_id,
        outcome=result.outcome.value,
        reason=result.reason,
    )
    return _end_for(result, engine.now())


async def _look(engine, job, task_id: uuid.UUID) -> Plan | End:
    """The decision. Reads, and on the way cancels the timers of a wait that is over."""
    now = engine.now()
    async with engine.scope(job.tenant_id) as session:
        task = await load_wait(session, task_id)
        if task is None:
            return Cancel("task_missing")
        over = await reason_to_stop(session, task, job_id=job.id, now=now)
        if over is not None:
            log_event(
                log,
                "holding_cancelled",
                tenant_id=job.tenant_id,
                trace_id=job.trace_id,
                job_id=job.id,
                task_id=task_id,
                reason=over.reason,
            )
            return over
        _version, settings = await current_settings(session)  # read now, at fire time
        due = task.received_at + timedelta(minutes=settings.holding_minutes)
        if now < due:
            return Wait(due)
        if task.holding_sent_at is not None:
            return Done("already_sent")
        if await sent_since(session, task.conversation_id, "holding", now - DAY) >= DAILY_HOLDING_CAP:
            return Done("capped")
    return Plan(task)


async def _recheck(engine, job, plan: Plan) -> Cancel | None:
    """Is the message still wanted? Asked again, in a fresh transaction, immediately before the gateway is called."""
    async with engine.scope(job.tenant_id) as session:
        task = await load_wait(session, plan.task.id)
        if task is None:
            return Cancel("task_missing")
        return await reason_to_stop(session, task, job_id=job.id, now=engine.now())
