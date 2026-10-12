from zoneinfo import ZoneInfo

import pytest

from clinic_integrations import FieldSpec, MappingConfig, MappingError, apply_mapping, suggest_mapping
from clinic_integrations.canonical import AppointmentIn

NY = ZoneInfo("America/New_York")


def test_transforms_normalise_messy_export_values():
    cfg = MappingConfig(
        fields={
            "email": FieldSpec(column="E-mail", transform="lower"),
            "phone": FieldSpec(column="Cell", transform="phone_e164"),
            "date_of_birth": FieldSpec(column="DOB", transform="date"),
            "amount_cents": FieldSpec(column="Total", transform="money_cents"),
        }
    )
    out, attrs = apply_mapping(
        {
            "E-mail": " Jane@Example.COM ",
            "Cell": "(415) 555-0134",
            "DOB": "03/07/1988",
            "Total": "$1,234.50",
            "Allergies": "latex",
        },
        cfg,
        NY,
    )
    assert out == {
        "email": "jane@example.com",
        "phone": "+14155550134",
        "date_of_birth": __import__("datetime").date(1988, 3, 7),
        "amount_cents": 123450,
    }
    assert attrs == {"Allergies": "latex"}  # unmapped columns are kept, not lost


def test_naive_datetimes_get_clinic_timezone():
    cfg = MappingConfig(fields={"starts_at": FieldSpec(column="When", transform="datetime")})
    out, _ = apply_mapping({"When": "10/01/2026 02:30 PM"}, cfg, NY)
    assert out["starts_at"].utcoffset().total_seconds() == -4 * 3600


def test_bad_value_raises_mapping_error():
    cfg = MappingConfig(fields={"phone": FieldSpec(column="Cell", transform="phone_e164")})
    with pytest.raises(MappingError):
        apply_mapping({"Cell": "12"}, cfg, NY)


def test_suggestion_handles_typical_emr_headers():
    m = suggest_mapping("appointment", ["Appointment ID", "Client ID", "Date", "Service", "Provider", "Status"])
    assert m.spec("external_id").column == "Appointment ID"
    assert m.spec("patient_external_id").column == "Client ID"
    assert m.spec("starts_at").column == "Date"
    assert m.spec("provider_name").column == "Provider"


def test_full_name_column_is_split():
    m = suggest_mapping("patient", ["Patient Name", "Email"])
    out, _ = apply_mapping({"Patient Name": "Rivera, Ana", "Email": "a@b.co"}, m, NY)
    assert (out["first_name"], out["last_name"]) == ("Ana", "Rivera")


@pytest.mark.parametrize(
    "raw,expected",
    [("Checked Out", "completed"), ("No-Show", "no_show"), ("Late Cancel", "cancelled"), ("Confirmed", "booked")],
)
def test_emr_status_spellings(raw, expected):
    appt = AppointmentIn(patient_external_id="p1", starts_at="2026-01-01T10:00:00+00:00", status=raw)
    assert appt.status == expected
