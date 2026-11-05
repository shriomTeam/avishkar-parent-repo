"""The ack has a 5 second goal, so the work before the provider is called must stay small. These tests count the SQL
statements (round trips) the engine runs, so a change that adds a query shows up here. The measured numbers are the
ceilings."""

from datetime import timedelta

from lr_engine import jobs_of_kind, make_engine, seed_text, tasks_of
from lr_gateway import FakeProvider, accepted, make_lead
from lr_intake import Counter

# gate (2) + claim (4) + the task step (set_config, the text, the settings, the task, two timer jobs, three checks = 9)
# + the gateway before the provider (8: set_config, already-sent check, conversation, clinic, settings, consent and the
# message and its first event)
BEFORE_THE_PROVIDER = 23
# after the provider: the gateway's sent event and last_outbound (3), the task stamp (2), the job marked done (2)
WHOLE_JOB = 30
# a second text of the same wait stops before the gateway: gate, claim, the task step, the job marked done
SECOND_JOB_OF_A_WAIT = 14


async def first_ack_costs(make_tenant, **seed):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    await seed_text(tenant, lead, **seed)
    seen = {}
    with Counter() as statements:

        async def hook(request):
            seen["before"] = len(statements)

        engine, provider, clock = make_engine(FakeProvider(accepted("SM" + "1" * 32), hook=hook))
        clock.advance(seconds=1)
        await engine.run_due(tenant)
    return tenant, seen["before"], statements


async def test_the_first_ack_of_a_wait_costs_few_statements_before_the_provider_is_called(make_tenant):
    _, before, statements = await first_ack_costs(make_tenant)
    print(f"\nfirst ack: {before} statements before the provider call, {len(statements)} in all")
    assert before <= BEFORE_THE_PROVIDER
    assert len(statements) <= WHOLE_JOB


async def test_the_task_is_written_before_the_message_and_so_before_the_provider(make_tenant):
    """From the statement log itself: the task, then its timers, and only afterwards the ack's message row."""
    _, before, statements = await first_ack_costs(make_tenant)
    text = [s.lstrip() for s in statements]
    task = next(i for i, s in enumerate(text) if s.startswith("INSERT INTO lead_response.tasks"))
    timers = [i for i, s in enumerate(text) if s.startswith("INSERT INTO lead_response.jobs")]
    ack_message = next(i for i, s in enumerate(text) if s.startswith("INSERT INTO lead_response.messages"))
    assert len(timers) == 2 and task < min(timers) < max(timers) < ack_message < before


async def test_a_second_text_of_the_same_wait_stops_before_the_gateway(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    await seed_text(tenant, lead, n=1)
    await seed_text(tenant, lead, n=2)
    engine, provider, clock = make_engine()
    clock.advance(seconds=1)
    await engine.run_due(tenant, limit=1)
    with Counter() as statements:
        await engine.run_due(tenant, limit=1)
    print(f"\nsecond job of the wait: {len(statements)} statements")
    assert len(provider.requests) == 1 and len(statements) <= SECOND_JOB_OF_A_WAIT


async def test_an_ack_that_is_not_due_costs_only_the_gate_and_an_empty_claim(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    engine, _, clock = make_engine()
    await seed_text(tenant, lead, run_at=clock() + timedelta(minutes=5))
    with Counter() as statements:
        assert await engine.run_due(tenant) == 0
    assert len(statements) <= 2 + 4  # the two gates, then a claim that finds nothing


async def test_a_blocked_ack_costs_no_more_than_a_sent_one(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant, consent=(False, "stop"))
    await seed_text(tenant, lead)
    engine, provider, clock = make_engine()
    clock.advance(seconds=1)
    with Counter() as statements:
        await engine.run_due(tenant)
    assert provider.requests == [] and len(statements) <= WHOLE_JOB
    assert len(await tasks_of(tenant)) == 1 and len(await jobs_of_kind(tenant, "holding")) == 1


async def test_the_task_step_does_not_grow_with_the_number_of_texts_already_in_the_wait(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    for n in range(1, 8):
        await seed_text(tenant, lead, n=n)
    engine, _, clock = make_engine()
    clock.advance(seconds=1)
    await engine.run_due(tenant, limit=1)
    costs = []
    for _ in range(6):
        with Counter() as statements:
            await engine.run_due(tenant, limit=1)
        costs.append(len(statements))
    assert max(costs) <= SECOND_JOB_OF_A_WAIT and len(set(costs)) == 1
