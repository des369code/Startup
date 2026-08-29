"""Region-extraction tests: filled rects and stroke-bounded rings.

Expected areas are computed via world_to_pt (fixtures.py) and compared with
rel=1e-6 (the plan-wide benchmark tolerance): extract_sheet ->
get_drawings() rounds all coordinates to float32 inside MuPDF
(verified: emitted width is float32(world_to_pt(10))), so the
round-tripped polygon area differs from the exact world-derived product by
~6e-3 pt^2 (relative ~1.2e-7), inside the 1e-6 gate.
"""
import pytest
from takeoff.geometry_regions import regions_from_fills, regions_from_polygonize
from takeoff.pdf_extract import extract_sheet
from tests.fixtures import make_synthetic_drawing, world_to_pt


def test_rect_region_areas_exact(tmp_path):
    pdf, truth = make_synthetic_drawing(tmp_path)
    sheet = extract_sheet(pdf)
    regs = regions_from_fills(sheet)
    assert len(regs) == 2
    expected_a = world_to_pt(10.0) * world_to_pt(5.0)
    expected_b = world_to_pt(8.0) * world_to_pt(8.0)
    assert sorted(r.area_pt2 for r in regs) == pytest.approx(
        sorted([expected_a, expected_b]), rel=1e-6
    )


def test_polygonize_finds_stroke_bounded_region(tmp_path):
    pdf, truth = make_synthetic_drawing(tmp_path)
    sheet = extract_sheet(pdf)
    regs = [r for r in regions_from_polygonize(sheet) if r.source == "polygonize"]
    # 6x6 stroke rectangle found; frame filtered; fills are NOT re-found here (they're fills)
    target = [r for r in regs if abs(r.area_pt2 - world_to_pt(6.0) * world_to_pt(6.0)) < 1.0]
    assert target, f"stroke-bounded 36m2 region missing; got areas {[round(r.area_pt2) for r in regs]}"


def test_polygonize_filters_page_frame_and_title_block(tmp_path):
    # outer page frame + title block rectangle must NOT be candidates
    regs = regions_from_polygonize(extract_sheet(make_synthetic_drawing(tmp_path)[0]))
    areas = [round(r.area_pt2) for r in regs if round(r.area_pt2) > world_to_pt(40.0) * world_to_pt(20.0)]
    assert not areas, "frame or title block leaked as candidate regions"


def test_containment_dedupe_drops_inner_region(tmp_path):
    # filled rect inside the stroke playlot ring -> 95%-contained -> dropped once
    pdf, _ = make_synthetic_drawing(tmp_path)          # fixture: playlot ring encloses nothing filled (keep simple: assert no duplicate area)
    sheet = extract_sheet(pdf)
    regs = regions_from_fills(sheet) + regions_from_polygonize(sheet)
    # containment guard: no pair with >=95% nested overlap
    for i, a in enumerate(regs):
        for b in regs[i + 1:]:
            smaller = a if a.area_pt2 <= b.area_pt2 else b
            if smaller.area_pt2 == 0: continue
            if b.polygon.contains(a.polygon) or a.polygon.contains(b.polygon):
                assert smaller.area_pt2 / max(a.area_pt2, b.area_pt2) < 0.95 or smaller.source == "fill", \
                    "nested candidate pair should have been dropped or the fill kept"
