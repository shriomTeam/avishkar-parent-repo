import itertools

import pytest

from clinic_lead_response.gateway.status import RANK, current_status, map_provider_status
from clinic_lead_response.gateway.types import MessageStatus as S

ORDER = ["queued", "sending", "sent", "delivered"]


def test_no_events_means_no_status():
    assert current_status([]) is None


@pytest.mark.parametrize("arrival", list(itertools.permutations(ORDER)))
def test_whatever_order_the_receipts_arrive_the_message_ends_delivered(arrival):
    assert current_status([(1, status) for status in arrival]) is S.DELIVERED


@pytest.mark.parametrize("arrival", list(itertools.permutations(["queued", "sending", "sent"])))
def test_without_delivery_the_furthest_state_wins(arrival):
    assert current_status([(1, status) for status in arrival]) is S.SENT


def test_a_late_sent_never_hides_delivered():
    assert current_status([(1, "sending"), (1, "delivered"), (1, "sent")]) is S.DELIVERED


def test_undelivered_after_sent_is_failed():
    assert current_status([(1, "sending"), (1, "sent"), (1, "failed")]) is S.FAILED


def test_the_latest_attempt_decides_so_a_failed_first_try_does_not_outrank_the_retry():
    events = [(1, "sending"), (1, "failed"), (2, "sending")]
    assert current_status(events) is S.SENDING
    assert current_status([*events, (2, "sent")]) is S.SENT


def test_delivered_on_an_earlier_attempt_is_final():
    assert current_status([(1, "sending"), (1, "delivered"), (2, "sending"), (2, "failed")]) is S.DELIVERED


def test_a_receipt_for_an_old_attempt_does_not_move_the_current_one():
    assert current_status([(1, "sending"), (2, "sending"), (1, "sent")]) is S.SENDING


def test_blocked_is_terminal_like_failed():
    assert current_status([(1, "blocked")]) is S.BLOCKED


def test_the_ranks_are_ordered():
    assert RANK[S.QUEUED] < RANK[S.SENDING] < RANK[S.SENT] < RANK[S.FAILED] < RANK[S.DELIVERED]


@pytest.mark.parametrize(
    ("provider", "ours"),
    [
        ("queued", S.QUEUED),
        ("accepted", S.QUEUED),
        ("scheduled", S.QUEUED),
        ("sending", S.SENDING),
        ("sent", S.SENT),
        ("delivered", S.DELIVERED),
        ("read", S.DELIVERED),
        ("undelivered", S.FAILED),
        ("failed", S.FAILED),
        (" Delivered ", S.DELIVERED),
        ("DELIVERED", S.DELIVERED),
    ],
)
def test_twilio_statuses_in_our_words(provider, ours):
    assert map_provider_status(provider) is ours


@pytest.mark.parametrize("provider", ["receiving", "received", "canceled", "partially_delivered", "", "mystery"])
def test_other_provider_words_are_ignored(provider):
    assert map_provider_status(provider) is None
