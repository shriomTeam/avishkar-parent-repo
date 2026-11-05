"""The three id-only names the engine adds to the log allow-list. Pure tests."""

import logging
import uuid

import pytest

from clinic_lead_response.gateway.log import ALLOWED_FIELDS, format_fields, log_event


@pytest.mark.parametrize("name", ["job_id", "task_id", "job_kind"])
def test_the_engine_fields_are_loggable(name):
    assert name in ALLOWED_FIELDS


def test_nothing_else_was_added():
    assert ALLOWED_FIELDS == {
        "tenant_id",
        "trace_id",
        "message_id",
        "job_id",
        "task_id",
        "job_kind",
        "lane",
        "purpose",
        "attempt",
        "outcome",
        "status",
        "reason",
        "provider",
        "provider_error_code",
        "http_status",
        "duration_ms",
        "to_masked",
        "queries",
    }


def test_the_ids_are_written_as_they_are_and_cannot_carry_free_text():
    job, task = uuid.uuid4(), uuid.uuid4()
    assert format_fields(job_id=job, task_id=task, job_kind="ack") == f"job_id={job} job_kind=ack task_id={task}"
    assert format_fields(job_kind="line one\nline two") == "job_kind=line_one_line_two"
    assert len(format_fields(job_kind="x" * 500)) < 80


@pytest.mark.parametrize("name", ["body", "text", "phone", "to", "from_number", "token", "error", "message", "payload"])
def test_free_text_and_personal_names_are_still_refused(name):
    assert name not in ALLOWED_FIELDS
    with pytest.raises(ValueError):
        format_fields(**{name: "x"})


def test_a_log_line_with_the_engine_fields(caplog):
    caplog.set_level(logging.INFO, logger="t")
    job = uuid.uuid4()
    log_event(logging.getLogger("t"), "job_failed", job_id=job, job_kind="holding", reason="RuntimeError")
    assert caplog.records[0].getMessage() == f"job_failed job_id={job} job_kind=holding reason=RuntimeError"
