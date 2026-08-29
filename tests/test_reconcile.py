"""Reconcile dimension callouts against measured run lengths (Task 9).

Trust-but-verify: a dimension callout PRINTED on the drawing must agree with
the engine's measured run length within 3%; a bigger disagreement is a
human-review flag. Words come straight from extract_sheet(pdf).words (fitz
tuples: x0, y0, x1, y1, text, block, line, word).
"""
import pytest

from takeoff.measure import measure
from takeoff.models import CandidateRun, Measurement, TakeoffResult
from takeoff.pdf_extract import extract_sheet
from takeoff.reconcile import dimension_callouts, reconcile_runs
from takeoff.testing import FakeSemantics
from tests.fixtures import make_synthetic_drawing


def _result(quantity, name="Water Pipe", unit="m"):
    return TakeoffResult(
        sheet_name="t", workspace="1 trade x 1 sheet",
        measurements=[Measurement(
            class_id="C4", class_name_en=name, measure="length",
            quantity=quantity, unit=unit, source_ids=["RUN0"], confidence=1.0,
        )],
        overflowed=False, qa=[],
    )


def _run(rid="RUN0"):
    return CandidateRun(
        id=rid, points=[(300.0, 300.0), (500.0, 300.0)],
        length_pt=200.0, bbox=(300.0, 300.0, 500.0, 300.0),
    )


def _word(x0, y0, x1, y1, text):
    return (x0, y0, x1, y1, text, 0, 0, 0)


def test_mismatch_reported():
    # The plan's sketch used a "23.6 m" callout — but 23.6 vs 24.0 is a 1.67%
    # difference, i.e. INSIDE the plan's own 3% tolerance, so it could never
    # REVIEW. 23.0 vs 24.0 is a 4.2% mismatch — a genuine flag.
    words = [_word(330.0, 290.0, 346.0, 310.0, "23.0"),
             _word(347.0, 290.0, 352.0, 310.0, "m")]
    lines = reconcile_runs(_result(24.0), words, [_run()])
    assert any("REVIEW" in line for line in lines)
    assert any("WATER PIPE" in line and "23.00" in line and "24.0" in line
               for line in lines)


def test_happy_path_no_review(tmp_path):
    # plan requirement: fixture drawing (callout "24.0 m" above the water-pipe
    # run), FakeSemantics measure, reconcile with the sheet's OWN words -> no
    # REVIEW: the pipe run is 24.0 m and the callout says 24.0 m.
    pdf, _truth = make_synthetic_drawing(tmp_path)
    outcome = measure(pdf, user_prompt="", semantics=FakeSemantics())
    sheet = extract_sheet(pdf)
    lines = reconcile_runs(outcome.result, sheet.words, outcome.runs)
    assert not any("REVIEW" in line for line in lines)
    # the callout is detected from real extraction (24.0 m near the pipe), so
    # the reconcile layer really did compare it, not just find nothing.
    vals = [v for v, _bbox in dimension_callouts(sheet.words)]
    assert any(v == pytest.approx(24.0) for v in vals)


def test_unitless_mm_callout():
    # bare 3-5-digit all-digit word near run linework = unitless mm callout:
    # "2400" -> 2.4 m (mm/1000). Detected, and a 2.4 m run reconciles clean.
    words = [_word(330.0, 290.0, 350.0, 310.0, "2400")]
    callouts = dimension_callouts(words)
    assert [(v, bbox) for v, bbox in callouts] == pytest.approx(
        [(2.4, (330.0, 290.0, 350.0, 310.0))]
    )
    lines = reconcile_runs(_result(2.4), words, [_run()])
    assert not any("REVIEW" in line for line in lines)


def test_unitless_mm_callout_gated_by_window():
    # a bare "2400" in a schedule far from the linework is NOT a run dimension:
    # 2.4 m callout 210 pt away from a 24.0 m run must be ignored (no REVIEW).
    words = [_word(330.0, 70.0, 350.0, 90.0, "2400")]
    lines = reconcile_runs(_result(24.0), words, [_run()])
    assert not any("REVIEW" in line for line in lines)
