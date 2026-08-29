"""Orchestrator tests: extraction -> semantics -> per-class math -> QA flags.

Ground truth comes from tests.fixtures (world_to_pt undo at 1:100). The
plan-wide tolerance is pytest.approx rel=1e-6.
"""
import pytest
from shapely.geometry import box

from takeoff.measure import _mixed_evidence, measure
from takeoff.models import CandidateRegion, ClassSpec
from takeoff.semantics import SheetSemantics
from takeoff.testing import FakeSemantics
from tests.fixtures import (
    make_busy_drawing,
    make_blank_drawing,
    make_mixed_drawing,
    make_synthetic_drawing,
)


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


class _ConflictingSemantics(FakeSemantics):
    """Claims the region id R0 in TWO maps (region_class + anchor_class)."""

    def sheet_semantics(self, sheet, regions, runs, anchors):
        sem = super().sheet_semantics(sheet, regions, runs, anchors)
        sem.anchor_class["R0"] = "C6"  # R0 already in region_class
        return sem


def test_conflicting_maps_dropped_and_flagged(tmp_path):
    # unique placement: an id in >1 map must not silently win by priority
    pdf, _ = make_synthetic_drawing(tmp_path)
    outcome = measure(pdf, semantics=_ConflictingSemantics())
    assert any(
        "semantics returned conflicting maps for id R0 — dropped" in line
        for line in outcome.result.qa
    )
    assert all("R0" not in m.source_ids for m in outcome.result.measurements)
    assert "Asphalt" not in {m.class_name_en for m in outcome.result.measurements}
    by_class = {m.class_name_en: m.quantity for m in outcome.result.measurements}
    assert by_class["Manhole"] == 2  # anchors unaffected


class _MixedSemantics(FakeSemantics):
    """Four fills + one polygonize region -> class "Mixed"; four clean fills
    -> class "Clean". The ring's area share is >20% while fills hold 4/5 of
    the candidate count: mixed evidence must fire (F4)."""

    def sheet_semantics(self, sheet, regions, runs, anchors):
        fills = [c for c in regions if c.source == "fill"]
        polys = [c for c in regions if c.source == "polygonize"]
        region_class: dict[str, str] = {}
        for i, c in enumerate(fills):
            region_class[c.id] = "C1" if i < 4 else "C2"
        for c in polys:
            region_class[c.id] = "C1"
        return SheetSemantics(
            scale_factor=100,
            classes=[
                ClassSpec(id="C1", name_en="Mixed", measure="area"),
                ClassSpec(id="C2", name_en="Clean", measure="area"),
            ],
            region_class=region_class, run_class={}, anchor_class={}, ignore_ids=[],
        )


def test_mixed_evidence_class_flagged(tmp_path):
    # F4 pin: mixed-source evidence -> confidence 0.5 + QA line; clean class -> 1.0
    pdf, truth = make_mixed_drawing(tmp_path)
    result = measure(pdf, semantics=_MixedSemantics()).result
    by_class = {m.class_name_en: m for m in result.measurements}
    assert by_class["Mixed"].confidence == 0.5
    assert any("class Mixed: mixed evidence — review" in line for line in result.qa)
    assert by_class["Mixed"].quantity == pytest.approx(truth["areas"]["mixed"], rel=1e-6)
    assert by_class["Clean"].confidence == 1.0
    assert not any("class Clean" in line for line in result.qa)


def test_mixed_evidence_guard_and_clean():
    # the predicate itself: <3 candidates -> no claim; 3+ one-source -> clean
    cls = ClassSpec(id="C1", name_en="T", measure="area")

    def region(source, fill_rgb, area_pt2):
        return CandidateRegion(
            id="R0", polygon=box(0, 0, 10.0, 10.0), bbox=(0.0, 0.0, 10.0, 10.0),
            area_pt2=area_pt2, fill_rgb=fill_rgb, source=source,
        )

    fills = [region("fill", (0, 0, 0), 50.0) for _ in range(4)]
    big = region("polygonize", None, 900.0)  # dominates area
    assert _mixed_evidence([big, fills[0]]) is False  # <3: no claim
    assert _mixed_evidence(fills[:3]) is False        # 3 clean fills: no claim
    assert _mixed_evidence([*fills, big]) is True     # 4/5 fills by count (0.8),
                                                      # poly holds 82% of the area
