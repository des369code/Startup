"""Orchestrator tests: extraction -> semantics -> per-class math -> QA flags.

Ground truth comes from tests.fixtures (world_to_pt undo at 1:100). The
plan-wide tolerance is pytest.approx rel=1e-6.
"""
import pytest

from takeoff.measure import measure
from takeoff.testing import FakeSemantics
from tests.fixtures import make_busy_drawing, make_blank_drawing, make_synthetic_drawing


def test_measure_area_matches_ground_truth(tmp_path):
    pdf, truth = make_synthetic_drawing(tmp_path)
    outcome = measure(pdf, user_prompt="", semantics=FakeSemantics())
    by_class = {m.class_name_en: m.quantity for m in outcome.result.measurements}
    assert by_class["Asphalt"] == pytest.approx(truth["areas"]["asphalt"], rel=1e-6)
    assert by_class["Planting"] == pytest.approx(truth["areas"]["planting"], rel=1e-6)


def test_count_truth(tmp_path):
    pdf, truth = make_synthetic_drawing(tmp_path)
    outcome = measure(pdf, user_prompt="", semantics=FakeSemantics())
    by_class = {m.class_name_en: m.quantity for m in outcome.result.measurements}
    assert by_class["Manhole"] == truth["counts"]["manhole"] == 2


def test_length_truth(tmp_path):
    pdf, truth = make_synthetic_drawing(tmp_path)
    outcome = measure(pdf, user_prompt="", semantics=FakeSemantics())
    by_class = {m.class_name_en: m.quantity for m in outcome.result.measurements}
    assert by_class["Water Pipe"] == pytest.approx(truth["runs"]["water_pipe"], rel=1e-6)


def test_overflow_cap_flags_qa(tmp_path):
    # busy sheet: 403 fills + 2 polygonize + 2 runs + 2 anchors = 409 candidates
    # > 400 -> overflowed must be True and the qa line present.
    pdf, truth = make_busy_drawing(tmp_path)
    outcome = measure(pdf, semantics=FakeSemantics())
    assert outcome.result.overflowed is True
    assert any("overflowed" in line for line in outcome.result.qa)
    assert truth["fill_count"] == 401  # grid count only; overflow is on totals


class _RaisingSemantics:
    """Any call on a blank sheet is a bug the test must surface."""

    def sheet_semantics(self, sheet, regions, runs, anchors):
        raise AssertionError("semantics must not be called on a blank sheet")

    def prompt_classes(self, user_prompt, classes):
        raise AssertionError("semantics must not be called on a blank sheet")


def test_blank_sheet_short_circuit(tmp_path):
    pdf, _ = make_blank_drawing(tmp_path)
    outcome = measure(pdf, semantics=_RaisingSemantics())
    assert outcome.result.measurements == []
    assert outcome.result.overflowed is False
    assert any("no candidates found on sheet" in line for line in outcome.result.qa)
