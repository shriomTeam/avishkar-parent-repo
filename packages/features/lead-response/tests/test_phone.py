import pytest

from clinic_lead_response.phone import InvalidPhone, normalise_phone


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("+14155550123", "+14155550123"),
        ("+1 (415) 555-0123", "+14155550123"),
        ("  +44 20 7946 0958 ", "+442079460958"),
        ("4155550123", "+14155550123"),
        ("(415) 555-0123", "+14155550123"),
        ("415.555.0123", "+14155550123"),
        ("14155550123", "+14155550123"),
        ("1-415-555-0123", "+14155550123"),
    ],
)
def test_recognised_numbers(raw, expected):
    assert normalise_phone(raw) == expected


@pytest.mark.parametrize("raw", ["", "abc", "555-0123", "+123", "+0123456789", "24155550123", "+1234567890123456"])
def test_unrecognised_numbers(raw):
    with pytest.raises(InvalidPhone):
        normalise_phone(raw)


def test_another_default_country():
    assert normalise_phone("2079460958", "44") == "+442079460958"


def test_the_error_never_contains_the_number():
    with pytest.raises(InvalidPhone) as error:
        normalise_phone("555-0199")
    assert "555" not in str(error.value)
