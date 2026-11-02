import pytest

from clinic_lead_response.gateway.keywords import (
    HELP_KEYWORDS,
    START_KEYWORDS,
    STOP_KEYWORDS,
    Keyword,
    classify_inbound,
)


def test_the_keyword_lists_are_twilios_documented_defaults():
    assert STOP_KEYWORDS == {"stop", "unsubscribe", "end", "quit", "stopall", "revoke", "optout", "cancel"}
    assert START_KEYWORDS == {"start", "unstop", "yes"}
    assert HELP_KEYWORDS == {"help"}


@pytest.mark.parametrize("word", sorted(STOP_KEYWORDS))
def test_every_stop_word(word):
    assert classify_inbound(word) is Keyword.STOP


@pytest.mark.parametrize("word", sorted(START_KEYWORDS))
def test_every_start_word(word):
    assert classify_inbound(word) is Keyword.START


def test_help():
    assert classify_inbound("help") is Keyword.HELP


@pytest.mark.parametrize("text", ["STOP", "Stop", "sToP", "  stop  ", "\nSTOP\t", "stop ", " STOP"])
def test_case_and_surrounding_whitespace_do_not_matter(text):
    assert classify_inbound(text) is Keyword.STOP


@pytest.mark.parametrize(
    "text",
    [
        "stop.",
        "stop!",
        "please stop",
        "stop texting me",
        "stop stop",
        "st op",
        "s-t-o-p",
        "stoppage",
        "unstoppable",
        "starting",
        "yes please",
        "I need help",
        "helpful",
        "help me",
        "YES!",
        "no",
        "hello",
        "",
        "   ",
        "\n",
    ],
)
def test_only_an_exact_word_counts_never_a_substring(text):
    assert classify_inbound(text) is None


def test_a_lookalike_unicode_word_is_not_a_keyword():
    assert classify_inbound("ѕtop") is None  # Cyrillic s
    assert classify_inbound("ＳＴＯＰ") is None  # full-width letters


def test_start_does_not_overlap_stop():
    assert not (STOP_KEYWORDS & START_KEYWORDS) and not (STOP_KEYWORDS & HELP_KEYWORDS)
