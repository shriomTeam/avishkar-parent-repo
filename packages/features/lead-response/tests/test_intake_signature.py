"""The inbound signature check. Pure tests: no database, no network."""

import random

import pytest
from lr_intake import PUBLIC, TOKEN, form_bytes, reference_signature, twilio_pairs

from clinic_lead_response.intake import signature
from clinic_lead_response.intake.parse import parse_form

# The worked example on https://www.twilio.com/docs/usage/security (read 2026-11-02, and recomputed here with Python's
# hmac on 2026-11-02 to get the same value, so it does not rest on the page text alone).
DOC_URL = "https://example.com/myapp.php?foo=1&bar=2"
DOC_TOKEN = "12345"
DOC_PAIRS = [
    ("CallSid", "CA1234567890ABCDE"),
    ("Caller", "+14158675310"),
    ("Digits", "1234"),
    ("From", "+14158675310"),
    ("To", "+18005551212"),
]
DOC_SIGNATURE = "L/OH5YylLD5NRKLltdqwSvS0BnU="

URL = f"{PUBLIC}/features/lead_response/in/sms/aaaaaaaa-1111-1111-1111-111111111111"
PAIRS = twilio_pairs()


def signed(url=URL, pairs=PAIRS, token=TOKEN) -> str:
    return reference_signature(token, url, pairs)


def test_twilios_documented_example():
    assert signature.expected_signature(DOC_TOKEN, DOC_URL, DOC_PAIRS) == DOC_SIGNATURE
    assert signature.is_valid(DOC_TOKEN, DOC_URL, DOC_PAIRS, DOC_SIGNATURE)


def test_the_reference_in_the_tests_agrees_with_twilios_example():
    assert reference_signature(DOC_TOKEN, DOC_URL, DOC_PAIRS) == DOC_SIGNATURE


def test_a_correct_signature_is_accepted():
    assert signature.is_valid(TOKEN, URL, PAIRS, signed())


def test_the_order_of_the_fields_does_not_matter():
    shuffled = PAIRS[:]
    random.Random(7).shuffle(shuffled)
    assert signature.is_valid(TOKEN, URL, shuffled, signed())


def test_the_signature_is_checked_over_the_decoded_form_body():
    body = form_bytes(twilio_pairs(Body="héllo wörld + 100% ✓"))
    pairs = parse_form(body)
    assert signature.is_valid(TOKEN, URL, pairs, reference_signature(TOKEN, URL, pairs))


@pytest.mark.parametrize("header", [None, "", " ", "abc", "=", "not base64 at all"])
def test_a_missing_or_nonsense_header_is_refused(header):
    assert not signature.is_valid(TOKEN, URL, PAIRS, header)


def test_a_header_with_padding_or_different_case_is_refused():
    good = signed()
    assert not signature.is_valid(TOKEN, URL, PAIRS, f" {good}")
    assert not signature.is_valid(TOKEN, URL, PAIRS, f"{good} ")
    assert not signature.is_valid(TOKEN, URL, PAIRS, good.swapcase())
    assert not signature.is_valid(TOKEN, URL, PAIRS, good[:-1])
    assert not signature.is_valid(TOKEN, URL, PAIRS, good + "A")


def test_a_header_with_non_ascii_text_is_refused_not_raised():
    assert not signature.is_valid(TOKEN, URL, PAIRS, "ü" * 28)
    assert not signature.is_valid(TOKEN, URL, PAIRS, "\udcff")  # a lone surrogate cannot be encoded strictly


def test_no_token_means_nothing_is_valid():
    assert not signature.is_valid("", URL, PAIRS, signed(token=""))


def test_another_token_is_refused():
    assert not signature.is_valid(TOKEN, URL, PAIRS, signed(token=TOKEN + "x"))
    assert not signature.is_valid(TOKEN + "x", URL, PAIRS, signed())


@pytest.mark.parametrize(
    "other",
    [
        URL.replace("https://", "http://"),
        URL.replace("api.example.test", "other.example.test"),
        URL.replace("api.example.test", "API.example.test"),
        URL + "/",
        URL.replace("/in/sms/", "/in/mms/"),
        URL.replace("/in/", "/status/"),
        URL.replace("aaaaaaaa-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"),
        URL.replace("aaaaaaaa-1111-1111-1111-111111111111", "aaaaaaaa-1111-1111-1111-111111111111?x=1"),
        URL.replace("aaaaaaaa-1111-1111-1111-111111111111", "aaaaaaaa-1111-1111-1111-111111111111".upper()),
    ],
    ids=["scheme", "host", "host-case", "slash", "channel", "route", "tenant", "query", "tenant-case"],
)
def test_a_different_url_is_refused(other):
    assert not signature.is_valid(TOKEN, other, PAIRS, signed())


def test_the_query_string_is_part_of_the_signed_url():
    url = signature.signed_url(PUBLIC, "/features/lead_response/status/sms/t", "m=abc")
    assert url.endswith("/status/sms/t?m=abc")
    assert signature.is_valid(TOKEN, url, PAIRS, signed(url))
    assert not signature.is_valid(TOKEN, url.replace("m=abc", "m=abd"), PAIRS, signed(url))
    assert not signature.is_valid(TOKEN, url.split("?")[0], PAIRS, signed(url))


def test_signed_url_without_a_query_has_no_question_mark():
    assert signature.signed_url(PUBLIC, "/x") == f"{PUBLIC}/x"


@pytest.mark.parametrize(
    "tamper",
    [
        lambda p: p + [("Extra", "1")],
        lambda p: p[1:],
        lambda p: [(n, v + "x") if n == "Body" else (n, v) for n, v in p],
        lambda p: [(n + "x", v) if n == "Body" else (n, v) for n, v in p],
        lambda p: [(n, "+14155550199") if n == "From" else (n, v) for n, v in p],
        lambda p: [(n, v) for n, v in p if n != "Body"],
        lambda p: p + [("Body", "twice")],
    ],
    ids=["added", "removed-first", "value", "name", "sender", "no-body", "repeated-name"],
)
def test_any_change_to_the_fields_is_refused(tamper):
    assert not signature.is_valid(TOKEN, URL, tamper(PAIRS), signed())


def test_a_signature_for_the_fields_alone_is_not_enough():
    assert not signature.is_valid(TOKEN, URL, PAIRS, reference_signature(TOKEN, "", PAIRS))


def test_empty_values_and_unicode_are_signed():
    pairs = twilio_pairs(Body="", MessagingServiceSid="", NumMedia="0") + [("Ünï", "✓ 日本語")]
    assert signature.is_valid(TOKEN, URL, pairs, reference_signature(TOKEN, URL, pairs))


def test_repeated_names_sign_every_value_in_order_of_value():
    pairs = [("A", "2"), ("A", "1"), ("B", "x")]
    sorted_pairs = [("A", "1"), ("A", "2"), ("B", "x")]
    assert signature.expected_signature(TOKEN, URL, pairs) == reference_signature(TOKEN, URL, sorted_pairs)
    one_value_lost = [("A", "2"), ("B", "x")]
    assert signature.expected_signature(TOKEN, URL, pairs) != signature.expected_signature(TOKEN, URL, one_value_lost)


def test_names_sort_by_code_point_not_by_case():
    pairs = [("b", "1"), ("B", "2"), ("a", "3")]
    by_code_point = [("B", "2"), ("a", "3"), ("b", "1")]
    assert signature.expected_signature(TOKEN, URL, pairs) == reference_signature(TOKEN, URL, by_code_point)


def test_the_comparison_is_the_constant_time_one(monkeypatch):
    calls = []
    real = signature.hmac.compare_digest

    def spy(a, b):
        calls.append((type(a), type(b)))
        return real(a, b)

    monkeypatch.setattr(signature.hmac, "compare_digest", spy)
    assert signature.is_valid(TOKEN, URL, PAIRS, signed())
    assert not signature.is_valid(TOKEN, URL, PAIRS, signed() + "x")
    assert calls == [(bytes, bytes), (bytes, bytes)]


def test_a_missing_header_never_reaches_the_comparison(monkeypatch):
    def boom(a, b):
        raise AssertionError("compared without a header")

    monkeypatch.setattr(signature.hmac, "compare_digest", boom)
    assert not signature.is_valid(TOKEN, URL, PAIRS, None)
    assert not signature.is_valid("", URL, PAIRS, "x")


def test_many_random_requests_agree_with_the_reference():
    rng = random.Random(11)
    alphabet = "abcXYZ019 +%&=é✓"
    for _ in range(200):
        pairs = [
            ("".join(rng.choices(alphabet, k=rng.randint(1, 6))), "".join(rng.choices(alphabet, k=rng.randint(0, 9))))
            for _ in range(rng.randint(0, 8))
        ]
        url = PUBLIC + "/p" + "".join(rng.choices("abc/?=&", k=rng.randint(0, 6)))
        assert signature.expected_signature(TOKEN, url, pairs) == reference_signature(TOKEN, url, pairs)
