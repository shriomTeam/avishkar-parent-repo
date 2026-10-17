"""The one definition of the Import CSV file: its columns, notes and example rows.

The parser, the template download and the in-page help all read this module, so they cannot drift.
Pure: no database, no clock, no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass

# kind: how a cell is read.  level: which rows must agree on the value (see parser.py).
TEXT, DATE, MONEY, CHOICE, FLAG = "text", "date", "money", "choice", "flag"
LINE, PATIENT, VISIT, SERVICE = "line", "patient", "visit", "service"

LINE_KINDS = ("service", "product", "membership", "package", "other")
VISIT_TYPES = ("consult", "treatment")
# The existing membership vocabulary (analysis/facts.py MEMBERSHIP_STATUSES) plus "none".
MEMBERSHIP_STATUSES = ("none", "active", "cancelled", "lapsed", "expired")
FLAG_TRUE = ("yes", "true", "1")
FLAG_FALSE = ("no", "false", "0")


@dataclass(frozen=True, slots=True)
class Column:
    name: str
    kind: str
    required: bool
    description: str
    if_missing: str  # what we cannot calculate without it, in plain words
    example: str
    values: tuple[str, ...] = ()
    level: str = LINE
    max_length: int = 500
    negative_ok: bool = False  # money only


COLUMNS: tuple[Column, ...] = (
    Column(
        "patient_id",
        TEXT,
        True,
        "Your own stable id for the patient. Repeat it on every row for that patient.",
        "Required.",
        "P-1001",
        max_length=64,
        level=PATIENT,
    ),
    Column(
        "patient_name",
        TEXT,
        False,
        "The name shown in the patient list.",
        'Patients are shown as "Patient <id>".',
        "Maya Rao",
        level=PATIENT,
    ),
    Column(
        "email",
        TEXT,
        False,
        "Used only to work out whether we can reach the patient. It is never shown or stored.",
        "We can't tell who can be reached by email.",
        "maya@example.com",
        level=PATIENT,
    ),
    Column(
        "phone",
        TEXT,
        False,
        "Used only to work out whether we can reach the patient. It is never shown or stored.",
        "We can't tell who can be reached by text.",
        "555-0101",
        level=PATIENT,
    ),
    Column(
        "email_consent",
        FLAG,
        False,
        "Has the patient agreed to emails? yes or no. Blank means unknown.",
        "Email counts as allowed when the patient has an address and hasn't opted out.",
        "yes",
        values=("yes", "no"),
        level=PATIENT,
    ),
    Column(
        "sms_consent",
        FLAG,
        False,
        "Has the patient agreed to texts? yes or no. Blank means unknown.",
        "Texts count as blocked unless the patient said yes (your clinic's opt-in rule).",
        "yes",
        values=("yes", "no"),
        level=PATIENT,
    ),
    Column(
        "visit_id",
        TEXT,
        False,
        "Groups the lines of one visit. Without it, one visit is the same patient on the same date.",
        "Nothing is lost.",
        "V-9001",
        max_length=64,
        level=VISIT,
    ),
    Column(
        "visit_date",
        DATE,
        True,
        "The clinic-local date of the visit, as YYYY-MM-DD. It can't be in the future.",
        "Required.",
        "2026-03-14",
    ),
    Column(
        "visit_type",
        CHOICE,
        False,
        "consult or treatment. Blank means treatment.",
        'Consult not converted shows "Not available".',
        "treatment",
        values=VISIT_TYPES,
        level=VISIT,
    ),
    Column(
        "line_kind",
        CHOICE,
        True,
        "What was sold on this line.",
        "Required.",
        "service",
        values=LINE_KINDS,
    ),
    Column(
        "service_name",
        TEXT,
        False,
        "The service, for example Botox. Required on service lines.",
        "No usual service per patient; every patient uses the standard rebooking interval.",
        "Botox",
    ),
    Column(
        "service_category",
        TEXT,
        False,
        "The service's category, for example Injectables. Used for rebooking intervals.",
        "Everyone uses the default rebooking interval.",
        "Injectables",
        level=SERVICE,
    ),
    Column(
        "provider_name",
        TEXT,
        False,
        "The person who saw the patient.",
        "Provider continuity shows as unknown.",
        "Dr. Lee",
    ),
    Column(
        "amount",
        MONEY,
        True,
        "Dollars with up to 2 decimals, for example 380.00. A minus sign marks a refund. "
        "No currency symbol or thousands separator. US dollars are assumed.",
        "Required.",
        "380.00",
        negative_ok=True,
    ),
    Column(
        "membership_status",
        CHOICE,
        False,
        "The patient's membership: none, active, cancelled, lapsed or expired.",
        'Churned member and Unused balance show "Not available".',
        "none",
        values=MEMBERSHIP_STATUSES,
        level=PATIENT,
    ),
    Column(
        "membership_ended_on",
        DATE,
        False,
        "When a cancelled, lapsed or expired membership ended, as YYYY-MM-DD.",
        "Churned members are found only by the general dormant rule.",
        "2026-01-31",
        level=PATIENT,
    ),
    Column(
        "prepaid_balance",
        MONEY,
        False,
        "The patient's unused prepaid balance in dollars (0 or more).",
        'Unused balance shows "Not available".',
        "150.00",
        level=PATIENT,
    ),
    Column(
        "next_appointment_date",
        DATE,
        False,
        "The patient's next booked appointment, as YYYY-MM-DD. Patients booked from today on are not dormant.",
        "Nobody is left out for having a future booking.",
        "2026-12-01",
        level=PATIENT,
    ),
    Column(
        "membership_monthly_fee",
        MONEY,
        False,
        "The monthly membership fee in dollars (0 or more). Used to value a churned member.",
        "Churned members are valued at $0.",
        "99.00",
        level=PATIENT,
    ),
    Column(
        "do_not_contact",
        FLAG,
        False,
        "yes if the patient asked not to be contacted. Blank means unknown. These patients are left out.",
        "Nobody is left out for this reason, and the results say so.",
        "no",
        values=("yes", "no"),
        level=PATIENT,
    ),
    Column(
        "deceased",
        FLAG,
        False,
        "yes if the patient has died. Blank means unknown. These patients are left out.",
        "Nobody is left out for this reason, and the results say so.",
        "no",
        values=("yes", "no"),
        level=PATIENT,
    ),
)

COLUMN_NAMES: tuple[str, ...] = tuple(c.name for c in COLUMNS)
BY_NAME: dict[str, Column] = {c.name: c for c in COLUMNS}

NOTES: tuple[str, ...] = (
    "One row per line sold at a visit: a service, a product, a membership payment or a package purchase. "
    "Patient details repeat on each of that patient's rows and must agree.",
    "A visit is counted only for a service or product line with an amount of 0 or more. Membership, package "
    "and other lines, and refunds (negative amounts), add to spend but never count as a visit.",
    "The first row must be the column names exactly as listed. Columns you don't have can be left out; a blank "
    "cell only means we can't calculate that part.",
    "Use a comma-separated UTF-8 file. Dates are YYYY-MM-DD. Amounts are dollars with no currency symbol.",
    "Your file is analysed on the spot and is never stored. Results show only in this browser tab and are "
    "cleared when you refresh the page.",
    "Return rates in a file analysis are always assumed. Measured rates come from past campaigns, which exist "
    "only in your saved data.",
)

# Three fictional patients. Each row must supply a value for every column (blank is fine).
TEMPLATE_ROWS: tuple[dict[str, str], ...] = (
    {
        "patient_id": "P-1001",
        "patient_name": "Maya Rao",
        "email": "maya@example.com",
        "phone": "555-0101",
        "email_consent": "yes",
        "sms_consent": "yes",
        "visit_id": "V-9001",
        "visit_date": "2026-03-14",
        "visit_type": "treatment",
        "line_kind": "service",
        "service_name": "Botox",
        "service_category": "Injectables",
        "provider_name": "Dr. Lee",
        "amount": "380.00",
        "membership_status": "none",
        "membership_ended_on": "",
        "prepaid_balance": "0.00",
        "next_appointment_date": "",
        "membership_monthly_fee": "",
        "do_not_contact": "no",
        "deceased": "no",
    },
    {
        "patient_id": "P-1001",
        "patient_name": "Maya Rao",
        "email": "maya@example.com",
        "phone": "555-0101",
        "email_consent": "yes",
        "sms_consent": "yes",
        "visit_id": "V-9001",
        "visit_date": "2026-03-14",
        "visit_type": "treatment",
        "line_kind": "product",
        "service_name": "SPF 50",
        "service_category": "Skincare",
        "provider_name": "Dr. Lee",
        "amount": "48.00",
        "membership_status": "none",
        "membership_ended_on": "",
        "prepaid_balance": "0.00",
        "next_appointment_date": "",
        "membership_monthly_fee": "",
        "do_not_contact": "no",
        "deceased": "no",
    },
    {
        "patient_id": "P-1002",
        "patient_name": "Dan Ortiz",
        "email": "",
        "phone": "555-0102",
        "email_consent": "",
        "sms_consent": "yes",
        "visit_id": "V-9002",
        "visit_date": "2025-11-02",
        "visit_type": "consult",
        "line_kind": "service",
        "service_name": "Consultation",
        "service_category": "Consults",
        "provider_name": "",
        "amount": "0.00",
        "membership_status": "none",
        "membership_ended_on": "",
        "prepaid_balance": "150.00",
        "next_appointment_date": "",
        "membership_monthly_fee": "",
        "do_not_contact": "",
        "deceased": "",
    },
)


def template_csv() -> str:
    """The header plus the example rows, as the file a clinic downloads."""
    import csv
    import io

    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(COLUMN_NAMES)
    for row in TEMPLATE_ROWS:
        writer.writerow([row[name] for name in COLUMN_NAMES])
    return out.getvalue()
