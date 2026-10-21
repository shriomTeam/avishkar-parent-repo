"""The Imported file page reads the file again in the browser (web/lib/csv-read.ts). These fixtures pin what that
reader must produce: the rows and start lines the server's own csv reader gives for the same bytes. The browser
reader is tested against the same JSON files by web/unit/csv-read.test.ts, so the two cannot drift apart.

To change a fixture, edit the .csv and regenerate its .json with `uv run python tests/test_csv_viewer_fixtures.py`.
"""

import csv
import io
import json
from datetime import date
from pathlib import Path

import pytest

from clinic_reactivation.csv_import.parser import CsvRejected, parse_csv

FIXTURES = Path(__file__).resolve().parents[1] / "web" / "unit" / "fixtures"
# Files the importer itself accepts. The others only exercise the reader.
VALID = {"plain", "quoted", "crlf-bom", "blank-lines", "bare-cr"}


def read_like_the_server(data: bytes) -> dict:
    """The record loop of csv_import.parser.parse_csv, without the column rules."""
    reader = csv.reader(io.StringIO(data.decode("utf-8-sig"), newline=""), strict=True)
    rows: list[list[str]] = []
    lines: list[int] = []
    start = 1
    for record in reader:
        row, start = start, reader.line_num + 1
        if not any(cell.strip() for cell in record):
            continue
        rows.append(record)
        lines.append(row)
    return {"rows": rows, "lines": lines}


def fixture_names() -> list[str]:
    return sorted(p.stem for p in FIXTURES.glob("*.csv"))


def test_there_are_fixtures():
    assert {"plain", "quoted", "crlf-bom", "blank-lines", "bare-cr", "errors", "mid-quote", "ragged"} <= set(
        fixture_names()
    )


@pytest.mark.parametrize("name", fixture_names())
def test_the_server_reader_gives_the_expected_rows(name):
    expected = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    assert read_like_the_server((FIXTURES / f"{name}.csv").read_bytes()) == expected


@pytest.mark.parametrize("name", sorted(VALID))
def test_valid_fixtures_really_are_accepted_by_the_importer(name):
    expected = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    parsed = parse_csv((FIXTURES / f"{name}.csv").read_bytes(), today=date(2026, 10, 18))
    assert len(parsed.lines) == len(expected["rows"]) - 1  # every data row is a line, the header is not


def test_the_errors_fixture_is_rejected_for_its_values_not_its_shape():
    with pytest.raises(CsvRejected) as raised:
        parse_csv((FIXTURES / "errors.csv").read_bytes(), today=date(2026, 10, 18))
    assert raised.value.code == "csv_invalid"


if __name__ == "__main__":
    for path in sorted(FIXTURES.glob("*.csv")):
        out = json.dumps(read_like_the_server(path.read_bytes()), ensure_ascii=False, indent=1) + "\n"
        path.with_suffix(".json").write_text(out, encoding="utf-8")
        print("wrote", path.with_suffix(".json").name)
