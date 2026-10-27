import csv
import io

import pytest

from clinic_api.routers.workspace_audit import csv_line


@pytest.mark.parametrize(
    "value", ["\tplain text", "\rplain text", "\t=1+1", "\r=1+1", "=1+1", "+1", "-1", "@SUM(A1)", "  =1"]
)
def test_csv_neutralizes_spreadsheet_control_characters_and_formulas(value):
    assert next(csv.reader(io.StringIO(csv_line([value])))) == ["'" + value]


def test_csv_keeps_normal_text_and_quotes_multiline_values():
    assert next(csv.reader(io.StringIO(csv_line(["A, B", "line1\nline2", "Normal name"])))) == [
        "A, B",
        "line1\nline2",
        "Normal name",
    ]
