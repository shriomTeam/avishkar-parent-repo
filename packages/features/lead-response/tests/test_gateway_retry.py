import pytest

from clinic_lead_response.gateway.retry import (
    RETRY_DELAYS,
    STUCK_AFTER_SECONDS,
    ErrorKind,
    classify_error,
    is_stuck,
    may_resend,
    next_retry,
    total_retry_seconds,
)
from clinic_lead_response.gateway.types import FailReason, Lane


@pytest.mark.parametrize("code", [21610])
def test_opt_out(code):
    assert classify_error(code=code, http_status=400) is ErrorKind.OPT_OUT


@pytest.mark.parametrize("code", [21211, 21214, 21217, 21614, 30005, 30006])
def test_invalid_numbers(code):
    assert classify_error(code=code) is ErrorKind.INVALID_NUMBER


@pytest.mark.parametrize("code", [21408, 21612, 21619, 21212, 30007, 30099, 99999])
def test_other_codes_are_permanent_and_unknown_ones_too(code):
    assert classify_error(code=code, http_status=400) is ErrorKind.PERMANENT


def test_bad_credentials_are_a_config_error():
    assert classify_error(code=20003, http_status=403) is ErrorKind.CONFIG


@pytest.mark.parametrize("code", [20429, 21611, 30003])
def test_retryable_codes(code):
    assert classify_error(code=code) is ErrorKind.RETRYABLE


def test_http_429_is_retryable_even_without_a_code():
    assert classify_error(http_status=429) is ErrorKind.RETRYABLE


@pytest.mark.parametrize("status", [500, 502, 503, 504, 501, 599])
def test_server_errors_are_ambiguous_because_the_message_may_exist(status):
    assert classify_error(http_status=status) is ErrorKind.AMBIGUOUS


def test_a_connection_that_never_opened_is_safe_to_retry():
    assert classify_error(transport="connect") is ErrorKind.RETRYABLE


@pytest.mark.parametrize("transport", ["timeout", "broken"])
def test_a_request_that_may_have_been_sent_is_ambiguous(transport):
    assert classify_error(transport=transport) is ErrorKind.AMBIGUOUS


def test_an_unknown_client_error_is_permanent():
    assert classify_error(http_status=400) is ErrorKind.PERMANENT
    assert classify_error(http_status=404) is ErrorKind.PERMANENT


@pytest.mark.parametrize("lane", list(Lane))
def test_three_retries_on_every_lane(lane):
    assert len(RETRY_DELAYS[lane]) == 3


def test_the_live_lane_gives_up_after_about_a_minute_and_follow_ups_wait_longer():
    assert total_retry_seconds(Lane.LIVE) == 63
    assert total_retry_seconds(Lane.FOLLOW_UP) == 2160


@pytest.mark.parametrize(("attempt", "delay"), [(1, 3), (2, 15), (3, 45)])
def test_live_backoff(attempt, delay):
    assert next_retry(Lane.LIVE, attempt, ErrorKind.RETRYABLE).retry_after_seconds == delay


def test_after_the_third_retry_the_gateway_gives_up():
    decision = next_retry(Lane.LIVE, 4, ErrorKind.RETRYABLE)
    assert decision.retry_after_seconds is None and decision.reason == FailReason.RETRIES_EXHAUSTED


@pytest.mark.parametrize("kind", [k for k in ErrorKind if k is not ErrorKind.RETRYABLE])
def test_only_retryable_errors_are_ever_retried(kind):
    assert next_retry(Lane.LIVE, 1, kind).retry_after_seconds is None


def test_an_ambiguous_send_is_never_retried():
    decision = next_retry(Lane.FOLLOW_UP, 1, ErrorKind.AMBIGUOUS)
    assert decision.retry_after_seconds is None and decision.reason == "ambiguous"


def test_a_longer_retry_after_from_the_provider_wins_and_is_capped():
    assert next_retry(Lane.LIVE, 1, ErrorKind.RETRYABLE, retry_after=30).retry_after_seconds == 30
    assert next_retry(Lane.LIVE, 1, ErrorKind.RETRYABLE, retry_after=1).retry_after_seconds == 3
    assert next_retry(Lane.LIVE, 1, ErrorKind.RETRYABLE, retry_after=10**6).retry_after_seconds == 3600


def test_stuck_deadlines():
    assert not is_stuck(Lane.LIVE, STUCK_AFTER_SECONDS[Lane.LIVE] - 1)
    assert is_stuck(Lane.LIVE, STUCK_AFTER_SECONDS[Lane.LIVE])
    assert STUCK_AFTER_SECONDS[Lane.FOLLOW_UP] > STUCK_AFTER_SECONDS[Lane.LIVE]


def test_no_receipt_is_never_resent_in_any_lane():
    assert may_resend(FailReason.NO_RECEIPT) is False


@pytest.mark.parametrize(
    ("reason", "allowed"),
    [
        ("20429", True),
        ("21611", True),
        ("30003", True),
        ("http_429", True),
        ("connect_error", True),
        ("21610", False),
        ("21211", False),
        ("30007", False),
        ("timeout", False),
        ("http_503", False),
        (FailReason.RETRIES_EXHAUSTED, False),
        (None, False),
    ],
)
def test_which_failure_reasons_may_be_resent(reason, allowed):
    assert may_resend(reason) is allowed
