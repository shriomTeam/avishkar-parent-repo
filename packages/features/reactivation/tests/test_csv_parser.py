"""The Import CSV parser: every error class, the agreement rules, and that no cell value is ever echoed."""

import csv
import io
from datetime import date

import pytest

from clinic_reactivation.csv_import import columns as cols
from clinic_reactivation.csv_import import parser
from clinic_reactivation.csv_import.parser import CsvRejected, parse_csv

TODAY = date(2026, 10, 18)
CANARY = "ZZcanaryZZ"


def row(**kw) -> dict[str, str]:
    base = {
        "patient_id": "P1", "visit_date": "2026-03-14", "line_kind": "service", "service_name": "Botox",
        "amount": "100.00",
    }  # fmt: skip
    base.update(kw)
    return base


def make(rows: list[dict[str, str]], header: list[str] | None = None, newline: str = "\n") -> bytes:
    header = header or list(dict.fromkeys(k for r in rows for k in r))
    out = io.StringIO()
    w = csv.writer(out, lineterminator=newline)
    w.writerow(header)
    for r in rows:
        w.writerow([r.get(h, "") for h in header])
    return out.getvalue().encode()


def reject(data: bytes) -> CsvRejected:
    with pytest.raises(CsvRejected) as info:
        parse_csv(data, today=TODAY)
    return info.value


def only_error(rows: list[dict[str, str]]):
    e = reject(make(rows))
    assert e.code == "csv_invalid"
    return e.errors


# --- the template and the column table ---------------------------------------------------------------------


def test_template_parses_and_covers_every_column():
    parsed = parse_csv(cols.template_csv().encode(), today=TODAY)
    assert parsed.columns == set(cols.COLUMN_NAMES)
    assert parsed.patients == 2 and len(parsed.lines) == 3
    assert all(set(r) == set(cols.COLUMN_NAMES) for r in cols.TEMPLATE_ROWS)


def test_every_column_has_help_and_an_example():
    for c in cols.COLUMNS:
        assert c.description and c.if_missing and c.example, c.name
    assert {c.name for c in cols.COLUMNS if c.required} == {
        "patient_id", "visit_date", "line_kind", "amount",
    }  # fmt: skip


def test_help_states_the_visit_rule_plainly():
    text = " ".join(cols.NOTES)
    assert "service or product line with an amount of 0 or more" in text


# --- file shape ----------------------------------------------------------------------------------------------


def test_empty_header_only_and_no_visits_have_their_own_codes():
    assert reject(b"").code == "csv_empty"
    assert reject(b"  \n \n").code == "csv_empty"
    assert reject(b"patient_id,visit_date,line_kind,amount\n").code == "csv_header_only"
    only_memberships = make([row(line_kind="membership", service_name="")])
    assert reject(only_memberships).code == "csv_no_visits"
    refund_only = make([row(amount="-5.00")])
    assert reject(refund_only).code == "csv_no_visits"


def test_encoding_bom_and_line_endings():
    assert reject(b"\xff\xfe\x00bad").code == "csv_bad_encoding"
    assert reject(b"patient_id\x00,x\n").code == "csv_bad_encoding"
    base = make([row()])
    assert parse_csv(b"\xef\xbb\xbf" + base, today=TODAY).patients == 1
    for nl in ("\r\n", "\r", "\n"):
        assert len(parse_csv(make([row(), row(patient_id="P2")], newline=nl), today=TODAY).lines) == 2


def test_quoted_fields_with_commas_and_newlines():
    data = make([row(patient_name='Rao, "Maya"\nJr', service_name="Botox, upper face")])
    ln = parse_csv(data, today=TODAY).lines[0]
    assert ln.service_name == "Botox, upper face" and ln.row == 2


def test_blank_lines_are_skipped_and_row_numbers_are_file_lines():
    data = b"patient_id,visit_date,line_kind,amount\n\nP1,2026-01-01,product,1.00\n\nP2,bad,product,1.00\n"
    (err,) = reject(data).errors
    assert (err.row, err.column) == (5, "visit_date")


def test_header_is_trimmed_case_insensitive_and_strict():
    data = b" Patient_ID , VISIT_DATE,Line_Kind,AMOUNT\nP1,2026-01-01,product,1.00\n"
    assert parse_csv(data, today=TODAY).patients == 1
    e = reject(b"patient_id,visit_date,line_kind,amount,nope,patient id\nP1,2026-01-01,product,1.00,x,y\n")
    assert e.code == "csv_invalid_header" and "nope" in e.message and "patient id" in e.message
    e = reject(b"patient_id,visit_date,line_kind,amount,amount\n")
    assert e.code == "csv_invalid_header" and "Repeated columns: amount" in e.message
    e = reject(b"patient_id,visit_date\n")
    assert "Missing required columns: line_kind, amount" in e.message


# --- cell errors ----------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("overrides", "column"),
    [
        ({"patient_id": ""}, "patient_id"),
        ({"patient_id": "x" * 65}, "patient_id"),
        ({"visit_date": "03/14/2026"}, "visit_date"),
        ({"visit_date": "2026-02-30"}, "visit_date"),
        ({"visit_date": "2026-10-19"}, "visit_date"),  # tomorrow
        ({"visit_date": "1999-12-31"}, "visit_date"),
        ({"line_kind": "refund"}, "line_kind"),
        ({"amount": "$5.00"}, "amount"),
        ({"amount": "1,000.00"}, "amount"),
        ({"amount": "5.123"}, "amount"),
        ({"amount": "1000000.01"}, "amount"),
        ({"amount": ""}, "amount"),
        ({"service_name": ""}, "service_name"),  # required on service lines
        ({"visit_type": "surgery"}, "visit_type"),
        ({"email_consent": "maybe"}, "email_consent"),
        ({"membership_status": "paused"}, "membership_status"),
        ({"membership_ended_on": "soon"}, "membership_ended_on"),
        ({"prepaid_balance": "-1.00"}, "prepaid_balance"),
        ({"membership_monthly_fee": "-1.00"}, "membership_monthly_fee"),
        ({"next_appointment_date": "tomorrow"}, "next_appointment_date"),
        ({"do_not_contact": "x"}, "do_not_contact"),
        ({"deceased": "x"}, "deceased"),
        ({"provider_name": "p" * 501}, "provider_name"),
    ],
)
def test_each_cell_error_class(overrides, column):
    errors = only_error([row(**overrides)])
    assert [(e.row, e.column) for e in errors] == [(2, column)]


def test_future_membership_and_next_appointment_dates_are_allowed():
    ok = row(membership_ended_on="2027-01-01", next_appointment_date="2027-01-01", membership_status="active")
    assert parse_csv(make([ok]), today=TODAY).patients == 1


def test_values_are_normalised():
    ln = parse_csv(
        make(
            [
                row(line_kind=" PRODUCT ", amount="-12.5", sms_consent="YES", email_consent="0", visit_type="Consult"),
                row(),
            ]
        ),
        today=TODAY,
    ).lines[0]
    assert (ln.line_kind, ln.amount, ln.sms_consent, ln.email_consent, ln.visit_type) == (
        "product", -1250, True, False, "consult",
    )  # fmt: skip


def test_wrong_cell_count_and_bad_quote():
    (err,) = reject(b"patient_id,visit_date,line_kind,amount\nP1,2026-01-01,product\n").errors
    assert (err.row, err.column) == (2, "(row)")
    e = reject(b'patient_id,visit_date,line_kind,amount\nP1,2026-01-01,"prod"uct,1.00\n')
    assert e.code == "csv_invalid"


def test_errors_are_capped_at_twenty_but_all_counted():
    e = reject(make([row(patient_id=f"P{i}", amount="bad") for i in range(45)]))
    assert len(e.errors) == 20 and e.total == 45
    assert "45 problems" in e.message


def test_no_cell_value_is_ever_echoed():
    bad = [
        row(patient_id=CANARY, visit_date=CANARY),
        row(patient_id=CANARY, amount=CANARY, line_kind=CANARY),
        row(patient_id=CANARY, visit_type=CANARY, email_consent=CANARY, prepaid_balance=CANARY),
        row(patient_id=CANARY, patient_name="A", email=CANARY + "@x.y"),
        row(patient_id=CANARY, patient_name="B", email="other@x.y"),
    ]
    e = reject(make(bad))
    blob = e.message + " ".join(f"{x.column} {x.reason}" for x in e.errors)
    assert CANARY not in blob and e.total >= 5
    # a malformed cell count and a bad quote carry no values either
    e2 = reject(f"patient_id,visit_date,line_kind,amount\n{CANARY},2026-01-01,product\n".encode())
    assert CANARY not in " ".join(x.reason for x in e2.errors)


# --- patient, visit and service agreement ------------------------------------------------------------------------


def test_patient_columns_must_agree_across_rows_and_name_the_rows():
    errors = only_error([
        row(patient_name="Maya Rao", phone="555-0101"),
        row(patient_name="maya  rao", phone="(555) 0101", visit_date="2026-04-01"),  # same after normalising
        row(patient_name="Maya Roe", visit_date="2026-05-01"),
    ])  # fmt: skip
    assert [(e.row, e.column) for e in errors] == [(4, "patient_name")]
    assert "row 2" in errors[0].reason


def test_blank_on_some_rows_is_fine():
    data = make([row(sms_consent="yes"), row(sms_consent="", visit_date="2026-04-01"), row(sms_consent="yes")])
    assert parse_csv(data, today=TODAY).lines[1].sms_consent is None


@pytest.mark.parametrize(
    ("column", "a", "b"),
    [
        ("email", "a@x.test", "b@x.test"),
        ("phone", "5550101", "5550102"),
        ("email_consent", "yes", "no"),
        ("sms_consent", "yes", "no"),
        ("membership_status", "active", "lapsed"),
        ("membership_ended_on", "2026-01-01", "2026-01-02"),
        ("prepaid_balance", "10.00", "10.01"),
        ("next_appointment_date", "2026-12-01", "2026-12-02"),
        ("membership_monthly_fee", "99.00", "98.00"),
        ("do_not_contact", "yes", "no"),
        ("deceased", "yes", "no"),
    ],
)
def test_every_patient_level_column_is_checked(column, a, b):
    errors = only_error([row(**{column: a}), row(**{column: b}, visit_date="2026-04-01")])
    assert [(e.row, e.column) for e in errors] == [(3, column)]


def test_same_value_on_different_patients_is_fine():
    data = make([row(patient_name="Sam"), row(patient_id="P2", patient_name="Alex")])
    assert parse_csv(data, today=TODAY).patients == 2


def test_visit_id_must_belong_to_one_patient_and_date():
    errors = only_error([row(visit_id="V1"), row(visit_id="V1", visit_date="2026-03-15")])
    assert [(e.row, e.column) for e in errors] == [(3, "visit_id")]
    errors = only_error([row(visit_id="V1"), row(patient_id="P2", visit_id="V1")])
    assert [(e.row, e.column) for e in errors] == [(3, "visit_id")]


def test_visit_type_must_agree_within_one_visit_only():
    errors = only_error([row(visit_type="consult"), row(visit_type="treatment", line_kind="product")])
    assert [(e.row, e.column) for e in errors] == [(3, "visit_type")]
    two_visits_one_day = [row(visit_id="V1", visit_type="consult"), row(visit_id="V2", visit_type="treatment")]
    assert parse_csv(make(two_visits_one_day), today=TODAY).patients == 1


def test_service_category_must_agree_for_the_same_service():
    errors = only_error([row(service_category="Injectables"), row(patient_id="P2", service_category="Laser")])
    assert [(e.row, e.column) for e in errors] == [(3, "service_category")]
    ok = [
        row(service_category="Injectables"),
        row(patient_id="P2", service_name=" botox ", service_category="injectables"),
    ]
    assert parse_csv(make(ok), today=TODAY).patients == 2


def test_service_name_column_is_required_when_the_file_has_service_lines():
    e = reject(b"patient_id,visit_date,line_kind,amount\nP1,2026-01-01,service,1.00\n")
    assert e.code == "csv_invalid" and e.errors[0].column == "service_name"


# --- limits ----------------------------------------------------------------------------------------------------------


def test_limits(monkeypatch):
    monkeypatch.setattr(parser, "MAX_BYTES", 100)
    e = reject(make([row(patient_id=f"P{i}") for i in range(10)]))
    assert (e.code, e.status) == ("csv_too_large", 413)
    monkeypatch.undo()
    monkeypatch.setattr(parser, "MAX_ROWS", 3)
    e = reject(make([row(patient_id=f"P{i}") for i in range(4)]))
    assert (e.code, e.status) == ("csv_too_many_rows", 413)
    monkeypatch.undo()
    monkeypatch.setattr(parser, "MAX_PATIENTS", 2)
    e = reject(make([row(patient_id=f"P{i}") for i in range(3)]))
    assert (e.code, e.status) == ("csv_too_many_patients", 413)
