"""The escalation has no tight deadline, but its path is counted all the same, so a change that adds a query shows up
here. The measured numbers are the ceilings."""

from datetime import timedelta

from lr_engine import jobs_of_kind
from lr_gateway import make_lead, set_settings
from lr_intake import Counter
from lr_wait import go_to, open_wait, staff_reply
from sqlalchemy import update

from clinic_core.database import tenant_session
from clinic_db.models.lead_response import Job

# gates (2) + claim (4) + the decision (set_config, the task, a staff reply, consent, the settings = 5)
# + the second look and the write in one transaction (set_config, the locked task, a staff reply, consent, the settings,
# the flag, the audit row = 7) + the job marked done (2)
ESCALATE = 20
# gates (2) + claim (4) + the decision up to where it stops (5) + the job put back, cancelled or finished (2)
STOPS_EARLY = 13


async def waiting(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    wait = await open_wait(tenant, lead)
    go_to(wait, 16)
    await wait.engine.run_due(tenant)  # the holding message goes out first
    return tenant, lead, wait


async def test_an_escalation_costs_a_fixed_small_number_of_statements(make_tenant):
    tenant, _, wait = await waiting(make_tenant)
    go_to(wait, 30)
    with Counter() as statements:
        assert await wait.engine.run_due(tenant) == 1
    print(f"\nescalation: {len(statements)} statements")
    assert len(statements) <= ESCALATE


async def test_a_job_put_back_because_the_target_was_lengthened_stops_early(make_tenant):
    tenant, _, wait = await waiting(make_tenant)
    await set_settings(tenant, holding_minutes=15, sla_minutes=60)
    go_to(wait, 30)
    with Counter() as statements:
        await wait.engine.run_due(tenant)
    assert len(statements) <= STOPS_EARLY


async def test_a_job_cancelled_by_a_staff_reply_stops_early(make_tenant):
    tenant, lead, wait = await waiting(make_tenant)
    await staff_reply(tenant, lead, wait.task.received_at + timedelta(minutes=2))
    go_to(wait, 30)
    with Counter() as statements:
        await wait.engine.run_due(tenant)
    assert len(statements) <= STOPS_EARLY


async def test_a_job_run_again_after_the_flag_was_set_stops_early(make_tenant):
    tenant, _, wait = await waiting(make_tenant)
    go_to(wait, 30)
    await wait.engine.run_due(tenant)
    async with tenant_session(tenant) as session:
        await session.execute(update(Job).where(Job.kind == "escalate").values(status="pending", run_at=wait.clock()))
    wait.clock.advance(minutes=1)
    with Counter() as statements:
        await wait.engine.run_due(tenant)
    assert len(statements) <= STOPS_EARLY
    assert (await jobs_of_kind(tenant, "escalate"))[0].last_error_code == "already_escalated"


async def test_an_escalation_that_is_not_due_costs_only_the_gates_and_an_empty_claim(make_tenant):
    tenant, _, wait = await waiting(make_tenant)
    go_to(wait, 20)
    with Counter() as statements:
        assert await wait.engine.run_due(tenant) == 0
    assert len(statements) <= 2 + 4
