"""The jobs table as a queue: claims are leases, completion is fenced, and failures end in a dead letter."""

import asyncio
import logging
import uuid
from contextlib import asynccontextmanager
from datetime import timedelta

import pytest
from lr_engine import NOW, add_job, all_jobs, get_job, make_queue
from lr_intake import Counter

from clinic_core.database import tenant_session
from clinic_lead_response.engine.queue import (
    BACKOFF_SECONDS,
    LEASE_EXPIRED,
    LEASE_SECONDS,
    MAX_CODE_LENGTH,
    enqueue_job,
    error_code,
)

LEASE = timedelta(seconds=LEASE_SECONDS)


# --- adding a job ---------------------------------------------------------------------------------------------------


async def enqueue(tenant, key="ack:1", **kw) -> bool:
    async with tenant_session(tenant) as session:
        return await enqueue_job(session, kind=kw.pop("kind", "holding"), key=key, run_at=kw.pop("run_at", NOW), **kw)


async def test_a_job_is_added_pending_with_the_ids_it_was_given(make_tenant):
    tenant = await make_tenant()
    trace = uuid.uuid4()
    assert await enqueue(tenant, "holding:t1", payload={"message_id": "m"}, trace_id=trace, run_at=NOW + LEASE)
    (job,) = await all_jobs(tenant)
    assert (job.kind, job.status, job.attempts, job.max_attempts) == ("holding", "pending", 0, 3)
    assert job.idempotency_key == "holding:t1" and job.payload == {"message_id": "m"} and job.trace_id == trace
    assert job.run_at == NOW + LEASE and job.locked_at is None and job.finished_at is None


async def test_the_same_key_never_adds_a_second_job(make_tenant):
    tenant = await make_tenant()
    assert await enqueue(tenant, "k") is True
    assert await enqueue(tenant, "k") is False
    assert await enqueue(tenant, "k", kind="escalate") is False
    assert len(await all_jobs(tenant)) == 1


async def test_the_same_key_in_two_clinics_is_two_jobs(make_tenant):
    a, b = await make_tenant(), await make_tenant()
    assert await enqueue(a, "k") and await enqueue(b, "k")
    assert len(await all_jobs(a)) == 1 and len(await all_jobs(b)) == 1


async def test_a_job_can_name_its_own_attempt_limit(make_tenant):
    tenant = await make_tenant()
    await enqueue(tenant, "k", max_attempts=5)
    assert (await all_jobs(tenant))[0].max_attempts == 5


async def test_ten_adds_at_once_with_one_key_make_one_job(make_tenant):
    tenant = await make_tenant()
    results = await asyncio.gather(*[enqueue(tenant, "same") for _ in range(10)])
    assert results.count(True) == 1 and len(await all_jobs(tenant)) == 1


# --- claiming -------------------------------------------------------------------------------------------------------


async def test_a_due_job_is_claimed_and_leased(make_tenant):
    tenant = await make_tenant()
    trace = uuid.uuid4()
    job_id = await add_job(tenant, kind="ack", payload={"message_id": "m"}, trace_id=trace)
    queue, _ = make_queue()
    (job,) = await queue.claim(tenant)
    assert (job.id, job.tenant_id, job.kind, job.attempts, job.max_attempts) == (job_id, tenant, "ack", 1, 3)
    assert job.payload == {"message_id": "m"} and job.trace_id == trace and job.token == NOW
    row = await get_job(tenant, job_id)
    assert row.status == "pending" and row.locked_at == NOW and row.run_at == NOW + LEASE and row.attempts == 1


async def test_a_job_that_is_not_due_yet_is_not_claimed(make_tenant):
    tenant = await make_tenant()
    await add_job(tenant, run_at=NOW + timedelta(seconds=1))
    queue, clock = make_queue()
    assert await queue.claim(tenant) == []
    clock.advance(seconds=1)
    assert len(await queue.claim(tenant)) == 1


@pytest.mark.parametrize("status", ["done", "failed", "cancelled"])
async def test_a_finished_job_is_never_claimed(make_tenant, status):
    tenant = await make_tenant()
    await add_job(tenant, status=status)
    queue, clock = make_queue()
    clock.advance(days=1)
    assert await queue.claim(tenant) == []


async def test_a_claimed_job_cannot_be_claimed_again_while_the_lease_lasts(make_tenant):
    tenant = await make_tenant()
    await add_job(tenant)
    queue, clock = make_queue()
    assert len(await queue.claim(tenant)) == 1
    clock.advance(seconds=LEASE_SECONDS - 1)
    assert await queue.claim(tenant) == []


async def test_when_the_lease_runs_out_the_job_is_claimed_again_and_counts_another_attempt(make_tenant):
    tenant = await make_tenant()
    job_id = await add_job(tenant)
    queue, clock = make_queue()
    (first,) = await queue.claim(tenant)
    clock.advance(seconds=LEASE_SECONDS)  # the worker died: nobody finished the job
    (second,) = await queue.claim(tenant)
    assert (first.attempts, second.attempts) == (1, 2)
    assert second.token > first.token
    assert (await get_job(tenant, job_id)).status == "pending"


async def test_the_limit_and_the_kinds_are_honoured(make_tenant):
    tenant = await make_tenant()
    for minute, kind in enumerate(("ack", "ack", "holding", "escalate", "help")):
        await add_job(tenant, kind=kind, run_at=NOW - timedelta(minutes=60 - minute))  # oldest first, in this order
    queue, _ = make_queue()
    assert [j.kind for j in await queue.claim(tenant, limit=2)] == ["ack", "ack"]
    assert [j.kind for j in await queue.claim(tenant, kinds=["holding", "escalate"])] == ["holding", "escalate"]
    assert [j.kind for j in await queue.claim(tenant, kinds=[])] == []
    assert [j.kind for j in await queue.claim(tenant)] == ["help"]


async def test_the_earliest_due_job_goes_first(make_tenant):
    tenant = await make_tenant()
    late = await add_job(tenant, run_at=NOW - timedelta(minutes=1))
    early = await add_job(tenant, run_at=NOW - timedelta(hours=1))
    queue, _ = make_queue()
    (only,) = await queue.claim(tenant, limit=1)
    assert only.id == early
    (next_one,) = await queue.claim(tenant, limit=1)
    assert next_one.id == late


async def test_one_clinics_jobs_are_not_claimed_through_another(make_tenant):
    a, b = await make_tenant(), await make_tenant()
    await add_job(a)
    queue, _ = make_queue()
    assert await queue.claim(b) == []
    assert len(await queue.claim(a)) == 1


# --- two workers ----------------------------------------------------------------------------------------------------


async def test_two_workers_claiming_one_job_at_once_get_it_once(make_tenant):
    tenant = await make_tenant()
    await add_job(tenant)
    first, _ = make_queue()
    second, _ = make_queue()
    results = await asyncio.gather(first.claim(tenant), second.claim(tenant))
    assert sorted(len(r) for r in results) == [0, 1]


async def test_a_worker_does_not_wait_behind_another_workers_open_claim(make_tenant):
    """Worker A has locked the oldest job and is slow to commit. Worker B must take the next job at once, not wait."""
    tenant = await make_tenant()
    first = await add_job(tenant, run_at=NOW - timedelta(minutes=2))
    second = await add_job(tenant, run_at=NOW - timedelta(minutes=1))
    locked, gate = asyncio.Event(), asyncio.Event()

    @asynccontextmanager
    async def slow_to_commit(tenant_id):
        async with tenant_session(tenant_id) as session:
            yield session
            locked.set()  # the claim's statements have run, the row is locked, the transaction is still open
            await gate.wait()

    slow_worker = make_queue(session_scope=slow_to_commit)[0]
    quick_worker = make_queue()[0]
    claim_a = asyncio.create_task(slow_worker.claim(tenant, limit=1))
    await asyncio.wait_for(locked.wait(), timeout=10)
    try:
        (taken,) = await asyncio.wait_for(quick_worker.claim(tenant, limit=1), timeout=5)
    finally:
        gate.set()
    (held,) = await claim_a
    assert (held.id, taken.id) == (first, second)


async def test_four_workers_share_twelve_jobs_without_overlap(make_tenant):
    tenant = await make_tenant()
    ids = {await add_job(tenant) for _ in range(12)}
    workers = [make_queue()[0] for _ in range(4)]
    results = await asyncio.gather(*[w.claim(tenant, limit=5) for w in workers])
    claimed = [job.id for batch in results for job in batch]
    assert len(claimed) == len(set(claimed)) == 12 and set(claimed) == ids


async def test_the_same_job_is_claimed_once_across_many_rounds(make_tenant):
    tenant = await make_tenant()
    for _ in range(6):
        await add_job(tenant)
    workers = [make_queue()[0] for _ in range(3)]
    seen: list[uuid.UUID] = []
    for _ in range(4):
        for batch in await asyncio.gather(*[w.claim(tenant, limit=2) for w in workers]):
            seen.extend(job.id for job in batch)
    assert len(seen) == len(set(seen)) == 6


# --- finishing, fenced by the lease ---------------------------------------------------------------------------------


async def test_complete_marks_the_job_done(make_tenant):
    tenant = await make_tenant()
    job_id = await add_job(tenant)
    queue, clock = make_queue()
    (job,) = await queue.claim(tenant)
    clock.advance(seconds=5)
    assert await queue.complete(job) is True
    row = await get_job(tenant, job_id)
    assert (row.status, row.locked_at, row.last_error_code) == ("done", None, None)
    assert row.finished_at == NOW + timedelta(seconds=5) and row.attempts == 1


async def test_complete_can_keep_a_fixed_word_about_how_it_ended(make_tenant):
    tenant = await make_tenant()
    job_id = await add_job(tenant)
    queue, _ = make_queue()
    (job,) = await queue.claim(tenant)
    assert await queue.complete(job, code="blocked")
    assert (await get_job(tenant, job_id)).last_error_code == "blocked"


async def test_cancel_keeps_the_reason(make_tenant):
    tenant = await make_tenant()
    job_id = await add_job(tenant, kind="holding")
    queue, _ = make_queue()
    (job,) = await queue.claim(tenant)
    assert await queue.cancel(job, "staff_reply")
    row = await get_job(tenant, job_id)
    assert (row.status, row.cancel_reason, row.locked_at) == ("cancelled", "staff_reply", None)
    assert row.finished_at == NOW


async def test_a_long_cancel_reason_is_cut_to_the_column(make_tenant):
    tenant = await make_tenant()
    job_id = await add_job(tenant)
    queue, _ = make_queue()
    (job,) = await queue.claim(tenant)
    assert await queue.cancel(job, "r" * 80)
    assert len((await get_job(tenant, job_id)).cancel_reason) == 32


async def test_a_job_put_back_to_wait_does_not_count_the_claim(make_tenant):
    tenant = await make_tenant()
    job_id = await add_job(tenant, kind="holding")
    queue, clock = make_queue()
    (job,) = await queue.claim(tenant)
    later = NOW + timedelta(minutes=10)
    assert await queue.reschedule(job, later)
    row = await get_job(tenant, job_id)
    assert (row.status, row.attempts, row.locked_at, row.run_at) == ("pending", 0, None, later)
    assert await queue.claim(tenant) == []
    clock.advance(minutes=10)
    (again,) = await queue.claim(tenant)
    assert again.attempts == 1


async def test_a_reschedule_can_count_the_attempt(make_tenant):
    tenant = await make_tenant()
    job_id = await add_job(tenant)
    queue, _ = make_queue()
    (job,) = await queue.claim(tenant)
    assert await queue.reschedule(job, NOW + timedelta(seconds=30), count_attempt=True)
    assert (await get_job(tenant, job_id)).attempts == 1


async def test_a_worker_that_lost_its_lease_changes_nothing(make_tenant):
    """Worker A is slow. Its lease runs out, worker B takes the job and finishes it. A then tries to finish too."""
    tenant = await make_tenant()
    job_id = await add_job(tenant)
    queue, clock = make_queue()
    (slow,) = await queue.claim(tenant)
    clock.advance(seconds=LEASE_SECONDS)
    (fast,) = await queue.claim(tenant)
    assert await queue.complete(fast, code="sent") is True
    assert await queue.complete(slow) is False
    assert await queue.cancel(slow, "late") is False
    assert await queue.reschedule(slow, NOW + timedelta(days=1)) is False
    assert await queue.fail_attempt(slow, "Late") is None
    row = await get_job(tenant, job_id)
    assert (row.status, row.last_error_code, row.cancel_reason) == ("done", "sent", None)


async def test_a_lost_lease_cannot_resurrect_a_job_someone_else_is_running(make_tenant):
    tenant = await make_tenant()
    job_id = await add_job(tenant)
    queue, clock = make_queue()
    (slow,) = await queue.claim(tenant)
    clock.advance(seconds=LEASE_SECONDS)
    (fast,) = await queue.claim(tenant)
    assert await queue.reschedule(slow, NOW) is False
    row = await get_job(tenant, job_id)
    assert row.locked_at == fast.token and row.attempts == 2


async def test_finishing_a_job_through_another_clinic_changes_nothing(make_tenant):
    a, b = await make_tenant(), await make_tenant()
    job_id = await add_job(a)
    queue, _ = make_queue()
    (job,) = await queue.claim(a)
    foreign = type(job)(**{**job.__dict__, "tenant_id": b})
    assert await queue.complete(foreign) is False
    assert (await get_job(a, job_id)).status == "pending"


async def test_a_finished_job_cannot_be_finished_twice(make_tenant):
    tenant = await make_tenant()
    await add_job(tenant)
    queue, _ = make_queue()
    (job,) = await queue.claim(tenant)
    assert await queue.complete(job) is True
    assert await queue.complete(job) is False
    assert await queue.cancel(job, "x") is False


# --- failing: backoff, then the dead-letter state -------------------------------------------------------------------


async def test_a_failed_attempt_backs_off_and_remembers_only_the_class_name(make_tenant):
    tenant = await make_tenant()
    job_id = await add_job(tenant)
    queue, _ = make_queue()
    (job,) = await queue.claim(tenant)
    assert await queue.fail_attempt(job, RuntimeError("cannot reach +14155550142 Zebra-Quartz")) == "retry"
    row = await get_job(tenant, job_id)
    assert (row.status, row.locked_at, row.last_error_code) == ("pending", None, "RuntimeError")
    assert row.run_at == NOW + timedelta(seconds=BACKOFF_SECONDS[0]) and row.attempts == 1
    assert "Zebra" not in str(row.last_error_code) and "4155550142" not in str(row.last_error_code)


async def test_the_backoff_grows_and_the_last_attempt_is_dead_lettered(make_tenant):
    tenant = await make_tenant()
    job_id = await add_job(tenant)
    queue, clock = make_queue()
    seen = []
    for attempt in (1, 2, 3):
        (job,) = await queue.claim(tenant)
        assert job.attempts == attempt
        seen.append(await queue.fail_attempt(job, ValueError("x")))
        row = await get_job(tenant, job_id)
        if attempt < 3:
            assert row.run_at == clock() + timedelta(seconds=BACKOFF_SECONDS[attempt - 1])
            clock.advance(seconds=BACKOFF_SECONDS[attempt - 1])
    assert seen == ["retry", "retry", "failed"]
    row = await get_job(tenant, job_id)
    assert (row.status, row.last_error_code, row.attempts) == ("failed", "ValueError", 3)
    assert row.finished_at is not None and row.locked_at is None
    clock.advance(days=30)
    assert await queue.claim(tenant) == []


async def test_a_job_with_one_allowed_attempt_fails_at_once(make_tenant):
    tenant = await make_tenant()
    job_id = await add_job(tenant, max_attempts=1)
    queue, _ = make_queue()
    (job,) = await queue.claim(tenant)
    assert await queue.fail_attempt(job, KeyError("k")) == "failed"
    assert (await get_job(tenant, job_id)).status == "failed"


async def test_a_job_that_keeps_crashing_is_dead_lettered_instead_of_run_again(make_tenant):
    """Three claims, three lease expiries (the worker died each time). The fourth claim does not run it."""
    tenant = await make_tenant()
    job_id = await add_job(tenant, trace_id=uuid.uuid4())
    queue, clock = make_queue()
    for expected in (1, 2, 3):
        (job,) = await queue.claim(tenant)
        assert job.attempts == expected
        clock.advance(seconds=LEASE_SECONDS)
    assert await queue.claim(tenant) == []
    row = await get_job(tenant, job_id)
    assert (row.status, row.last_error_code, row.attempts) == ("failed", LEASE_EXPIRED, 3)
    assert row.finished_at == clock()


async def test_a_job_still_inside_its_last_lease_is_not_dead_lettered(make_tenant):
    tenant = await make_tenant()
    job_id = await add_job(tenant, attempts=2)
    queue, clock = make_queue()
    (job,) = await queue.claim(tenant)
    assert job.attempts == 3
    clock.advance(seconds=LEASE_SECONDS - 1)
    assert await queue.claim(tenant) == []
    assert (await get_job(tenant, job_id)).status == "pending"


async def test_the_error_code_is_the_class_name_or_a_fixed_word_and_never_longer_than_the_column():
    assert error_code(RuntimeError("secret text")) == "RuntimeError"
    assert error_code("blocked") == "blocked"
    assert len(error_code("x" * 500)) == MAX_CODE_LENGTH
    assert len(error_code(type("N" * 200, (Exception,), {})("m"))) == MAX_CODE_LENGTH


# --- what is logged -------------------------------------------------------------------------------------------------


async def test_failures_are_logged_with_ids_and_no_exception_text(make_tenant, caplog):
    tenant = await make_tenant()
    trace = uuid.uuid4()
    job_id = await add_job(tenant, kind="holding", trace_id=trace, max_attempts=2)
    caplog.set_level(logging.DEBUG, logger="lead_response")
    queue, clock = make_queue()
    (job,) = await queue.claim(tenant)
    await queue.fail_attempt(job, RuntimeError("Zebra-Quartz +14155550142"))
    clock.advance(seconds=BACKOFF_SECONDS[0])
    (job,) = await queue.claim(tenant)
    await queue.fail_attempt(job, RuntimeError("Zebra-Quartz +14155550142"))
    lines = [r.getMessage() for r in caplog.records]
    assert any(line.startswith("job_retry ") for line in lines) and any(
        line.startswith("job_failed ") for line in lines
    )
    for line in lines:
        assert f"tenant_id={tenant}" in line and f"trace_id={trace}" in line and f"job_id={job_id}" in line
        assert "job_kind=holding" in line and "reason=RuntimeError" in line
        assert "Zebra" not in line and "4155550142" not in line


async def test_a_dead_letter_is_logged_when_it_is_found(make_tenant, caplog):
    tenant = await make_tenant()
    job_id = await add_job(tenant, attempts=3, trace_id=uuid.uuid4())
    caplog.set_level(logging.DEBUG, logger="lead_response")
    queue, _ = make_queue()
    assert await queue.claim(tenant) == []
    (line,) = [r.getMessage() for r in caplog.records if r.getMessage().startswith("job_dead ")]
    assert f"job_id={job_id}" in line and f"reason={LEASE_EXPIRED}" in line


# --- cost -----------------------------------------------------------------------------------------------------------


async def test_a_claim_costs_a_fixed_small_number_of_statements(make_tenant):
    tenant = await make_tenant()
    for _ in range(5):
        await add_job(tenant)
    queue, _ = make_queue()
    with Counter() as statements:
        jobs = await queue.claim(tenant, limit=5)
    print(f"\nclaim of {len(jobs)} jobs: {len(statements)} statements")
    assert len(jobs) == 5 and len(statements) <= 4  # set_config, the dead-letter sweep, the lock, the claim


async def test_an_empty_claim_costs_the_same(make_tenant):
    tenant = await make_tenant()
    queue, _ = make_queue()
    with Counter() as statements:
        assert await queue.claim(tenant) == []
    assert len(statements) <= 4
