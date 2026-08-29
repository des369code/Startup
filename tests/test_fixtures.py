# tests/test_fixtures.py
import fitz

from tests.fixtures import (
    make_blank_drawing,
    make_busy_drawing,
    make_synthetic_drawing,
    make_synthetic_drawing_v2,
    world_to_pt,
)


def test_fixture_pdf_is_readable(tmp_path):
    pdf, truth = make_synthetic_drawing(tmp_path)
    doc = fitz.open(pdf)
    assert doc.page_count == 1
    assert truth["areas"]["asphalt"] == 50.0
    assert truth["scale_factor"] == 100


def test_synthetic_ground_truth_is_exact(tmp_path):
    _, truth = make_synthetic_drawing(tmp_path)
    assert truth["areas"]["planting"] == 64.0
    assert truth["runs"]["water_pipe"] == 24.0
    assert truth["counts"]["manhole"] == 2
    assert truth["polygonize_area"] == 36.0
    # sampled length of the cubic Bezier (t = 0..1 in 8 steps); locked so any
    # change to the curve or the sampler fails here first.
    assert truth["curve_run_pt"] == 179.07943634084018


def test_synthetic_v2_ground_truth(tmp_path):
    # Task 13: v2 = harder fixture (3 areas, 2-digit anchor class, scale 1:200).
    pdf, truth = make_synthetic_drawing_v2(tmp_path)
    assert fitz.open(pdf).page_count == 1
    assert len(truth["areas"]) == 3
    assert truth["scale_factor"] == 200
    # distinct from v1's 50/64/36 values so benchmarks can tell them apart
    assert truth["areas"]["asphalt"] == 144.0
    assert truth["areas"]["planting"] == 80.0
    assert truth["areas"]["paving"] == 60.0
    assert truth["counts"]["manhole"] == 2


def test_world_to_pt_scale_exact():
    assert world_to_pt(1, 100) == 28.34645669291339
    # round-trip: 10 m x 5 m at 1:100 recovers exactly 50.0 m^2
    assert (
        world_to_pt(10) / world_to_pt(1) * (world_to_pt(5) / world_to_pt(1)) == 50.0
    )


def test_busy_drawing_fill_count(tmp_path):
    pdf, truth = make_busy_drawing(tmp_path)
    doc = fitz.open(pdf)
    assert doc.page_count == 1
    assert truth["fill_count"] == 401


def test_blank_drawing_zero_candidates(tmp_path):
    pdf, truth = make_blank_drawing(tmp_path)
    assert fitz.open(pdf).page_count == 1
    assert truth["candidates"] == 0
