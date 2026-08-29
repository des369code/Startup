"""Multi-sheet per-trade rollup tests (the wedge demo).

Cross-sheet sums per (class, measure, unit) — with the honesty constraint:
reconciled must be False, because same-structure-on-two-sheets dedup is a
later phase. Two fixture copies of the same sheet (same geometry, different
file stems) must sum to exactly 2x the single-sheet truth.
"""
import shutil

import pytest
from openpyxl import load_workbook

from takeoff.aggregate import TradeRollup, aggregate, merge_rollups
from takeoff.models import Measurement, TakeoffResult
from takeoff.report import add_rollup_sheet, write_xlsx
from takeoff.testing import FakeSemantics
from tests.fixtures import make_synthetic_drawing


def _result(sheet_name: str, class_id: str = "C1", quantity: float = 50.0) -> TakeoffResult:
    return TakeoffResult(
        sheet_name=sheet_name, workspace="1 trade x 1 sheet",
        measurements=[Measurement(
            class_id=class_id, class_name_en="Asphalt", measure="area",
            quantity=quantity, unit="m2", source_ids=["R1"], confidence=1.0)],
        overflowed=False, qa=[],
    )


def _rollup(class_name_en: str, measure: str = "area", total: float = 100.0,
            unit: str = "m2") -> TradeRollup:
    return TradeRollup(class_name_en=class_name_en, measure=measure, total=total,
                       unit=unit, per_sheet=[], reconciled=False)


def test_rollup_sums_across_sheets(tmp_path):
    d1 = tmp_path / "a"; d1.mkdir()
    d2 = tmp_path / "b"; d2.mkdir()
    p1, _ = make_synthetic_drawing(d1)
    p2, _ = make_synthetic_drawing(d2)
    # both fixtures are saved as "synthetic.pdf" — rename the second copy so
    # the rollup's per-sheet traceability shows two distinct sheets
    p2 = shutil.copyfile(p2, str(tmp_path / "sheet2.pdf"))
    rollups = aggregate([p1, p2], semantics=FakeSemantics())
    asphalt = [r for r in rollups if r.class_name_en == "Asphalt"][0]
    assert asphalt.total == pytest.approx(100.0, rel=1e-6)  # 50 + 50
    assert asphalt.reconciled is False                      # honesty flag
    assert len(asphalt.per_sheet) == 2                      # one entry per sheet


def test_rollup_key_merges_even_when_ids_differ():
    # rollup key is (class_name_en, measure, unit) — per-sheet class ids
    # collide, so a key built on ids would split one trade across rows
    rollups = merge_rollups([_result("plan", "C1"), _result("section", "X9")])
    assert len(rollups) == 1
    asphalt = rollups[0]
    assert asphalt.total == pytest.approx(100.0, rel=1e-6)
    assert asphalt.per_sheet == [("plan", 50.0), ("section", 50.0)]
    assert asphalt.reconciled is False


def test_add_rollup_sheet(tmp_path):
    out = write_xlsx(_result("demo"), str(tmp_path / "out.xlsx"))
    rollups = [_rollup(class_name_en="Water Pipe", measure="length", total=12.5, unit="m"),
               _rollup(class_name_en="Asphalt")]
    assert add_rollup_sheet(out, rollups) == out
    wb = load_workbook(out)
    assert "rollup" in wb.sheetnames
    ws = wb["rollup"]
    assert [c.value for c in ws[1]] == ["class_name_en", "measure", "total", "unit", "reconciled"]
    assert ws["A1"].font.bold is True
    assert ws["A2"].value == "Asphalt"       # sorted by class_name_en
    assert ws["A3"].value == "Water Pipe"
    assert ws["E2"].value is False and ws["E3"].value is False
