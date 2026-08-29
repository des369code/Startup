"""Report writer tests: JSON full dump, CSV, XLSX (openpyxl).

Values are hand-built (no measure() call) so failures localize to the
writers, not the orchestrator.
"""
import csv
import io
import json

import pytest
from openpyxl import load_workbook

from takeoff.measure import measure
from takeoff.models import ClassSpec, Measurement, TakeoffResult
from takeoff.report import to_csv, to_json, write_xlsx
from takeoff.testing import FakeSemantics
from tests.fixtures import make_synthetic_drawing

COLUMNS = [
    "sheet_name", "class_name_en", "class_name_ms", "measure",
    "quantity", "unit", "source_ids", "confidence", "qa_flags",
]


def _result() -> TakeoffResult:
    return TakeoffResult(
        sheet_name="demo", workspace="2 trades x 1 sheet",
        measurements=[
            Measurement(
                class_id="C1", class_name_en="Asphalt", class_name_ms="Aspal",
                measure="area", quantity=25.75, unit="m2",
                source_ids=["R1", "R2"], confidence=1.0,
            ),
            Measurement(
                class_id="C4", class_name_en="Water Pipe", measure="length",
                quantity=12.5, unit="m", source_ids=["RUN0"], confidence=0.5,
            ),
        ],
        overflowed=False,
        qa=["mixed evidence — review", "scale text ambiguous or missing"],
    )


def test_json_roundtrip():
    data = json.loads(to_json(_result()))
    assert data["sheet_name"] == "demo"
    assert data["workspace"] == "2 trades x 1 sheet"
    assert data["overflowed"] is False
    assert len(data["measurements"]) == 2
    assert data["measurements"][0]["quantity"] == 25.75
    assert data["measurements"][0]["class_name_ms"] == "Aspal"
    assert data["qa"] == ["mixed evidence — review", "scale text ambiguous or missing"]


def test_csv_header():
    rows = list(csv.reader(io.StringIO(to_csv(_result()))))
    assert rows[0] == COLUMNS


def test_csv_data_row_order_and_qa_flags():
    rows = list(csv.reader(io.StringIO(to_csv(_result()))))
    assert rows[1] == [
        "demo", "Asphalt", "Aspal", "area", "25.75", "m2",
        "R1; R2", "1.0", "mixed evidence — review; scale text ambiguous or missing",
    ]
    # qa_flags is sheet-level: identical in every row (header excluded).
    assert rows[1][8] == rows[2][8]


def test_xlsx_writes_and_reads_back(tmp_path):
    out = write_xlsx(_result(), str(tmp_path / "out.xlsx"))
    assert out == str(tmp_path / "out.xlsx")
    ws = load_workbook(out)["takeoff"]
    assert [c.value for c in ws[1]] == COLUMNS
    assert ws["A1"].font.bold is True
    assert ws.freeze_panes == "A2"
    assert ws["E2"].value == 25.75      # quantity col, first measurement
    assert ws["C2"].value == "Aspal"    # class_name_ms populated
    assert ws["I2"].value == "mixed evidence — review; scale text ambiguous or missing"


class _MSFake(FakeSemantics):
    """Same scripted mapping, but C1 carries name_ms (like a real legend)."""

    def sheet_semantics(self, sheet, regions, runs, anchors):
        sem = super().sheet_semantics(sheet, regions, runs, anchors)
        old = sem.classes[0]
        sem.classes[0] = ClassSpec(id=old.id, name_en=old.name_en,
                                   measure=old.measure, name_ms="Aspal")
        return sem


def test_measurement_carries_name_ms_from_class_spec(tmp_path):
    pdf, _ = make_synthetic_drawing(tmp_path)
    outcome = measure(pdf, user_prompt="", semantics=_MSFake())
    asphalt = next(m for m in outcome.result.measurements
                   if m.class_name_en == "Asphalt")
    assert asphalt.class_name_ms == "Aspal"
