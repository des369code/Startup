"""Synthetic JKR-style drawing fixtures with exact ground truth.

These drawings are the oracle every later task (geometry extraction,
measurement, semantics, CLI) tests against. All world-space dimensions are
converted to PDF points with :func:`world_to_pt` at the sheet's scale, so the
ground-truth areas/runs are exactly recoverable by undoing that conversion.

Sheet format: A4 landscape (842 x 595 pt), scale 1:100.
"""

import fitz

PAGE_W, PAGE_H = 842.0, 595.0
SCALE_FACTOR = 100
V2_SCALE_FACTOR = 200


def world_to_pt(value_m: float, factor: int = 100) -> float:
    """World metres @ given scale (e.g. 1:100 -> factor 100) -> PDF points."""
    return value_m * 1000.0 * (72 / 25.4) / factor


def _m(value_m: float) -> float:
    """Metres -> points at the fixture's 1:100 scale."""
    return world_to_pt(value_m, SCALE_FACTOR)


def _m2(value_m: float) -> float:
    """Metres -> points at the fixture v2's 1:200 scale."""
    return world_to_pt(value_m, V2_SCALE_FACTOR)


def _bezier(p0, c1, c2, p1, n=8):
    """Sample a cubic Bezier at t = 0, 1/n, ..., 1. Returns n+1 (x, y) points.

    Ground truth for the curved run is measured over these samples and is
    recorded in ``curve_run_pt``; run measurement must use the same sampler.
    """
    pts = []
    for i in range(n + 1):
        t = i / n
        u = 1.0 - t
        x = (u * u * u * p0[0] + 3 * u * u * t * c1[0]
             + 3 * u * t * t * c2[0] + t * t * t * p1[0])
        y = (u * u * u * p0[1] + 3 * u * u * t * c1[1]
             + 3 * u * t * t * c2[1] + t * t * t * p1[1])
        pts.append((x, y))
    return pts


def _bezier_length(p0, c1, c2, p1, n=8):
    pts = _bezier(p0, c1, c2, p1, n)
    return sum(
        ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5
        for a, b in zip(pts, pts[1:])
    )


def _new_page():
    doc = fitz.open()
    page = doc.new_page(width=PAGE_W, height=PAGE_H)
    return doc, page


def _draw_synthetic_sheet(page):
    """Draw every standard fixture element. Returns (curve_run_pt,
    curve_chain_run_pt) — bezier-sampled length, and the full stroke chain
    lead-in + sampled bezier length (both in pt)."""
    d = 1.0  # stroke width

    # page frame (outer border, stroke only) - exercises frame filtering
    page.draw_rect(fitz.Rect(8, 8, 834, 587), color=(0, 0, 0), width=d)

    # asphalt: filled 10 m x 5 m -> 50.0 m2
    ax0, ay0 = 72.0, 40.0
    page.draw_rect(
        fitz.Rect(ax0, ay0, ax0 + _m(10), ay0 + _m(5)),
        color=(0, 0, 0), fill=(0, 0, 0), width=d,
    )

    # planting: filled 8 m x 8 m -> 64.0 m2
    px0, py0 = 400.0, 40.0
    page.draw_rect(
        fitz.Rect(px0, py0, px0 + _m(8), py0 + _m(8)),
        color=(0, 0, 0), fill=(0.6, 0.6, 0.6), width=d,
    )

    # playlot: stroke-only 6 m x 6 m ring, 4 separate draw_line segments
    rx0, ry0 = 72.0, 220.0
    p_a = (rx0, ry0)
    p_b = (rx0 + _m(6), ry0)
    p_c = (rx0 + _m(6), ry0 + _m(6))
    p_d = (rx0, ry0 + _m(6))
    for a, b in ((p_a, p_b), (p_b, p_c), (p_c, p_d), (p_d, p_a)):
        page.draw_line(a, b, color=(0, 0, 0), width=d)

    # water pipe run: stroke polyline, 4 segments of 6 + 8 + 4 + 6 m = 24 m
    q0 = (300.0, 300.0)
    q1 = (q0[0] + _m(6), q0[1])
    q2 = (q1[0] + _m(8), q1[1])
    q3 = (q2[0], q2[1] + _m(4))
    q4 = (q3[0] - _m(6), q3[1])
    for a, b in ((q0, q1), (q1, q2), (q2, q3), (q3, q4)):
        page.draw_line(a, b, color=(0, 0, 0), width=d)

    # curved run: stroke lead-in line + cubic Bezier
    cs = (400.0, 470.0)
    c1, c2, ce = (470.0, 450.0), (520.0, 450.0), (570.0, 490.0)
    page.draw_line((300.0, 470.0), cs, color=(0, 0, 0), width=d)
    page.draw_bezier(cs, c1, c2, ce, color=(0, 0, 0), width=d)
    curve_run_pt = _bezier_length(cs, c1, c2, ce)

    # dimension callout placed right above the pipe run's first segment
    page.insert_text((330.0, 292.0), "24.0 m", fontsize=8, fontname="helv")
    # manhole label texts
    page.insert_text((404.0, 283.0), "MH-01", fontsize=8, fontname="helv")
    page.insert_text((590.0, 283.0), "MH-02", fontsize=8, fontname="helv")

    # legend box (stroke) + words
    page.draw_rect(fitz.Rect(60, 500, 200, 572), color=(0, 0, 0), width=d)
    for i, word in enumerate(
        ("LEGEND / PETUNJUK", "ASPHALT", "PLANTING", "WATER PIPE", "MANHOLE")
    ):
        page.insert_text((72.0, 512.0 + i * 14.0), word, fontsize=8, fontname="helv")

    # title block scale text
    page.insert_textbox(
        fitz.Rect(650, 495, 826, 520), "SCALE 1:100", fontsize=10, fontname="helv"
    )
    # full chain oracle for run extraction (takeoff.geometry_runs extracts the
    # whole stroke as one chain): lead-in chord + sampled bezier polyline,
    # both sampler-derived inside the fixture, no hardcoded lengths.
    lead_in_pt = ((cs[0] - 300.0) ** 2 + (cs[1] - 470.0) ** 2) ** 0.5
    return curve_run_pt, lead_in_pt + curve_run_pt


def _ground_truth(curve_run_pt, curve_chain_run_pt, **extra):
    truth = {
        "areas": {"asphalt": 50.0, "planting": 64.0},
        "runs": {"water_pipe": 24.0},
        "counts": {"manhole": 2},
        "scale_factor": SCALE_FACTOR,
        "polygonize_area": 36.0,
        "curve_run_pt": curve_run_pt,
        "curve_chain_run_pt": curve_chain_run_pt,
    }
    truth.update(extra)
    return truth


def make_synthetic_drawing(tmp_path) -> tuple[str, dict]:
    """Writes a JKR-style sheet PDF. Returns (pdf_path, ground_truth).

    ground_truth dict: {"areas": {"asphalt": 50.0, "planting": 64.0},
                        "runs": {"water_pipe": 24.0},
                        "counts": {"manhole": 2},
                        "scale_factor": 100,
                        "curve_run_pt": bezier-sampled length,
                        "curve_chain_run_pt": lead-in + sampled bezier length}
    """
    doc, page = _new_page()
    curve_run_pt, curve_chain_run_pt = _draw_synthetic_sheet(page)
    pdf = str(tmp_path / "synthetic.pdf")
    doc.save(pdf)
    doc.close()
    return pdf, _ground_truth(curve_run_pt, curve_chain_run_pt)


def make_synthetic_drawing_v2(tmp_path) -> tuple[str, dict]:
    """Task 13's harder scenario: 3 filled areas + a 2-digit anchor class,
    scale 1:200. Returns (pdf_path, ground_truth) with len(areas) == 3,
    scale_factor == 200, and area values distinct from v1 (50/64/36) so
    benchmarks can tell the two sheets apart.

    Same A4 landscape + drawing helpers as v1 (deterministic, on-grid, so the
    rel 1e-6 exactness tolerances hold). No stroke-only rings and no runs: the
    filled rects' outline rings are re-found by polygonize and deduped away by
    measure(), so the v2 candidate set is exactly 3 fills + 2 anchors — which
    is what FakeSemantics's scripted v2 map keys on (fills by index, anchors
    -> the anchor class)."""
    doc, page = _new_page()
    d = 1.0

    # asphalt: filled 12 m x 12 m -> 144.0 m2
    page.draw_rect(fitz.Rect(72.0, 40.0, 72.0 + _m2(12), 40.0 + _m2(12)),
                   color=(0, 0, 0), fill=(0, 0, 0), width=d)
    # planting: filled 8 m x 10 m -> 80.0 m2
    page.draw_rect(fitz.Rect(400.0, 40.0, 400.0 + _m2(8), 40.0 + _m2(10)),
                   color=(0, 0, 0), fill=(0.6, 0.6, 0.6), width=d)
    # paving: filled 10 m x 6 m -> 60.0 m2
    page.draw_rect(fitz.Rect(72.0, 300.0, 72.0 + _m2(10), 300.0 + _m2(6)),
                   color=(0, 0, 0), fill=(0.8, 0.8, 0.8), width=d)

    # 2-digit MH anchor labels (the v2 "2-digit anchor class")
    page.insert_text((404.0, 283.0), "MH-12", fontsize=8, fontname="helv")
    page.insert_text((590.0, 283.0), "MH-34", fontsize=8, fontname="helv")

    page.insert_textbox(
        fitz.Rect(650, 495, 826, 520), "SCALE 1:200", fontsize=10, fontname="helv"
    )
    pdf = str(tmp_path / "synthetic-v2.pdf")
    doc.save(pdf)
    doc.close()
    return pdf, {
        "areas": {"asphalt": 144.0, "planting": 80.0, "paving": 60.0},
        "counts": {"manhole": 2},
        "scale_factor": V2_SCALE_FACTOR,
    }


def make_busy_drawing(tmp_path) -> tuple[str, dict]:
    """Writes a sheet with 401+ small closed fills (for overflow tests) plus the
    standard fixture classes. ground_truth["fill_count"] = 401."""
    doc, page = _new_page()
    curve_run_pt, curve_chain_run_pt = _draw_synthetic_sheet(page)

    # 401 fills: 50 mm x 50 mm rects at 60 mm pitch (21 cols x 20 rows grid).
    # 50 mm site -> 0.5 mm paper -> ~1.417 pt side -> ~2.01 pt^2 area, above
    # regions_from_fills' default min_area_pt2=0.5 so all 401 survive as
    # candidates and the >400 overflow triggers.
    side = _m(0.05)
    pitch = _m(0.06)
    ox, oy = 700.0, 80.0
    for i in range(401):
        col, row = i % 21, i // 21
        x = ox + col * pitch
        y = oy + row * pitch
        page.draw_rect(
            fitz.Rect(x, y, x + side, y + side),
            color=(0, 0, 0), fill=(0, 0, 0), width=0.5,
        )

    pdf = str(tmp_path / "busy.pdf")
    doc.save(pdf)
    doc.close()
    return pdf, _ground_truth(curve_run_pt, curve_chain_run_pt, fill_count=401)


def make_mixed_drawing(tmp_path) -> tuple[str, dict]:
    """M5 mixed-evidence sheet: 8 small filled rects (0.1 m side, ~8 pt^2 —
    above the min-area filters) + one large stroke-only ring (8 m x 8 m).

    A class mixing 4 fills + the ring has 4/5 of its candidate count in fills
    but ~99% of its area in the ring: the F4 fill-border relationship that
    chain-consistency must flag. ground_truth["areas"] = {"mixed": 64.04,
    "clean": 0.04}."""
    doc, page = _new_page()
    for i in range(8):
        x = 72.0 + (i % 4) * 60.0
        y = 60.0 + (i // 4) * 60.0
        page.draw_rect(
            fitz.Rect(x, y, x + _m(0.1), y + _m(0.1)),
            color=(0, 0, 0), fill=(0, 0, 0), width=0.5,
        )
    page.draw_rect(fitz.Rect(300.0, 300.0, 300.0 + _m(8), 300.0 + _m(8)),
                   color=(0, 0, 0), width=1.0)
    page.insert_textbox(
        fitz.Rect(650, 495, 826, 520), "SCALE 1:100", fontsize=10, fontname="helv"
    )
    pdf = str(tmp_path / "mixed.pdf")
    doc.save(pdf)
    doc.close()
    return pdf, {
        "areas": {"mixed": 4 * 0.1 * 0.1 + 8.0 * 8.0, "clean": 4 * 0.1 * 0.1},
        "scale_factor": SCALE_FACTOR,
    }


def make_blank_drawing(tmp_path) -> tuple[str, dict]:
    """Writes a sheet with NO geometry — just the title block text (for the
    zero-candidate short-circuit test). ground_truth["candidates"] = 0."""
    doc, page = _new_page()
    page.insert_textbox(
        fitz.Rect(650, 495, 826, 520), "SCALE 1:100", fontsize=10, fontname="helv"
    )
    pdf = str(tmp_path / "blank.pdf")
    doc.save(pdf)
    doc.close()
    return pdf, {"candidates": 0, "scale_factor": SCALE_FACTOR}
