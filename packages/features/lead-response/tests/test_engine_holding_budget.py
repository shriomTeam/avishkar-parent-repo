"""The holding message has no tight deadline, but its path is counted all the same, so a change that adds a query
shows up here. The measured numbers are the ceilings."""

from datetime import timedelta

from lr_gateway import make_lead, set_settings
from lr_intake import Counter
from lr_wait import go_to, open_wait, opt_out, staff_reply

# gates (2) + claim (4) + the decision (set_config, the task, a staff reply, consent, the settings, the count = 6)
# + the second look (set_config, the task, a staff reply, consent = 4) + the gateway before the provider (8)
BEFORE_THE_PROVIDER = 24
# after the provider: the gateway's sent event and last_outbound (3), the task stamp (2), the job marked done (2)
WHOLE_SEND = 31
# gates (2) + claim (4) + the decision (up to the point it stops) + the job put back or cancelled (2)
STOPS_EARLY = 13


async def test_a_holding_message_costs_few_statements_before_the_provider_is_called(make_tenant):
    tenant = await make_tenant()
    wait = await open_wait(tenant, await make_lead(tenant))
    go_to(wait, 15)
    seen = {}
    with Counter() as statements:

        async def hook(request):
            seen["before"] = len(statements)

        wait.provider.hook = hook
        await wait.engine.run_due(tenant)
    print(f"\nholding: {seen['before']} before the provider call, {len(statements)} in all")
    assert seen["before"] <= BEFORE_THE_PROVIDER and len(statements) <= WHOLE_SEND


async def test_a_job_put_back_because_the_timer_was_lengthened_stops_early(make_tenant):
    tenant = await make_tenant()
    wait = await open_wait(tenant, await make_lead(tenant))
    await set_settings(tenant, holding_minutes=40, sla_minutes=60)
    go_to(wait, 15)
    with Counter() as statements:
        await wait.engine.run_due(tenant)
    assert len(statements) <= STOPS_EARLY


async def test_a_job_cancelled_by_a_staff_reply_stops_early(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    wait = await open_wait(tenant, lead)
    await staff_reply(tenant, lead, wait.task.received_at + timedelta(minutes=1))
    go_to(wait, 15)
    with Counter() as statements:
        await wait.engine.run_due(tenant)
    assert len(statements) <= STOPS_EARLY


async def test_a_job_cancelled_by_a_stop_stops_early(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    wait = await open_wait(tenant, lead)
    await opt_out(tenant, lead)
    go_to(wait, 15)
    with Counter() as statements:
        await wait.engine.run_due(tenant)
    assert len(statements) <= STOPS_EARLY


async def test_a_holding_job_that_is_not_due_costs_only_the_gates_and_an_empty_claim(make_tenant):
    tenant = await make_tenant()
    wait = await open_wait(tenant, await make_lead(tenant))
    go_to(wait, 5)
    with Counter() as statements:
        assert await wait.engine.run_due(tenant) == 0
    assert len(statements) <= 2 + 4
