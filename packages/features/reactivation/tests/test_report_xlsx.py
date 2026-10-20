"""The report workbook is written in the browser by web/lib/report.ts, with no library. This opens a sample of it with
openpyxl, a reader written by other people, so a mistake in the zip or the XML shows up here and not in a clinic's
Excel. Skipped where node or openpyxl is not installed."""

import shutil
import subprocess
from pathlib import Path

import pytest

openpyxl = pytest.importorskip("openpyxl")
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")

SCRIPT = Path(__file__).resolve().parents[1] / "web" / "unit" / "make-sample-report.ts"


@pytest.fixture(scope="module")
def workbook(tmp_path_factory):
    out = tmp_path_factory.mktemp("report") / "sample.xlsx"
    subprocess.run([NODE, str(SCRIPT), str(out)], check=True, capture_output=True, timeout=60)
    return openpyxl.load_workbook(out)


def test_sheets_are_named_in_order_and_within_excels_limits(workbook):
    names = workbook.sheetnames
    assert names[0] == "Summary"
    assert names[1] == "One-and-done"
    assert names[2] == "A very long patient group name"  # cut at 31 characters
    assert all(len(n) <= 31 for n in names) and len(names) == 3  # unavailable types have no sheet


def test_the_summary_says_who_when_and_where_from_with_the_sensitivity_note(workbook):
    ws = workbook["Summary"]
    rows = {r[0].value: r[1].value for r in ws.iter_rows(min_row=1, max_row=12) if r[0].value}
    assert ws["A1"].value == "Dormant patients report"
    assert rows["Clinic"] == 'Riverside & Sons <Skin> "Clinic"'
    assert rows["Report date"] == "2026-10-20"
    assert rows["Source"] == "File march-export.csv, not saved"
    assert "patient names" in rows["Note"] and "delete it when you are done" in rows["Note"]
    assert rows["Dormant patients"] == 3 and rows["Patients analysed"] == 12
    assert rows["Recoverable revenue, low"] == pytest.approx(1234.56)
    assert rows["Recoverable revenue, high"] == pytest.approx(2345.67)
    groups = {r[0].value: [c.value for c in r] for r in ws.iter_rows(min_row=16) if r[0].value}
    assert groups["One-and-done"][:2] == ["One-and-done", 2]
    assert groups["Churned member"][:2] == ["Churned member", "Not available"]


def test_a_group_sheet_has_heading_count_headers_and_the_patients(workbook):
    ws = workbook["One-and-done"]
    assert ws["A1"].value == "One-and-done"
    assert ws["A2"].value == "Visited once and has not come back."
    assert ws["A3"].value == "2 patients"
    assert [c.value for c in ws[5]][:3] == ["Patient", "Patient id", "Status"]
    assert ws.freeze_panes == "A6"
    first, second = [[c.value for c in ws[r]] for r in (6, 7)]
    assert first[:8] == ["Maya Rao", "p1", "Dormant", "Botox", "2026-01-02", 291, "High", 70]
    assert first[8] == pytest.approx(250.5) and first[9] == pytest.approx(20.04) and first[10] == pytest.approx(37.58)
    assert first[11:] == ["Facial", "One visit; No return"]
    assert second[0] == "Zoë ☃ O'Brien" and second[12] == "a & b; <c>"  # unicode and XML characters survive
    assert ws["I6"].number_format == '"$"#,##0.00'  # money cells carry a currency format


def test_text_that_looks_like_a_formula_stays_text_and_bad_characters_are_dropped(workbook):
    ws = workbook[workbook.sheetnames[2]]
    cell = ws["A6"]
    assert cell.data_type == "s" and cell.value == '=HYPERLINK("http://x")'  # control character removed, no formula
    assert ws["J6"].value is None and ws["G6"].value is None  # empty, not "None" or zero
