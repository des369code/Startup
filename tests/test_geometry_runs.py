"""Run-extraction tests: open polylines from strokes, closed rings excluded.

The wrong-number guard: the fixture's 6x6 m stroke-bounded playlot ring has a
24 m perimeter — the SAME value as the true 24 m water-pipe run. If the
perimeter leaked in as a run, test_straight_run_length_exact would pass FOR
THE WRONG REASON. The closed-ring tests exist precisely for that trap.
"""
from takeoff.geometry_runs import runs_from_strokes
from takeoff.pdf_extract import extract_sheet
from tests.fixtures import make_synthetic_drawing, world_to_pt


def test_straight_run_length_exact(tmp_path):
    pdf, truth = make_synthetic_drawing(tmp_path)
    sheet = extract_sheet(pdf)
    runs = runs_from_strokes(sheet)
    straight = [r for r in runs if abs(r.length_pt - world_to_pt(24.0)) < 1.0]
    assert straight, f"24 m run not found; got {[r.length_pt for r in runs]}"


def test_closed_ring_is_not_a_run(tmp_path):
    # The fixture's 6x6 stroke-bounded playlot has a 24 m perimeter. If the
    # perimeter leaked in as a run, it would pass test_straight_run_length_exact
    # FOR THE WRONG REASON (same value as the true 24 m run). Assert perimeters
    # are excluded: no run of length == playlot perimeter unless it is the real
    # open run; and with exclude_closed=False the closed chain is marked closed.
    pdf, truth = make_synthetic_drawing(tmp_path)
    sheet = extract_sheet(pdf)
    runs = runs_from_strokes(sheet)                       # default: excluded
    perim = world_to_pt(6.0) * 4                          # 24 m in pt
    closed_run_lengths = [r.length_pt for r in runs if r.closed]
    assert closed_run_lengths == [], "closed rings leaked as runs"
    all_runs = runs_from_strokes(sheet, exclude_closed=False)
    circle = [r for r in all_runs if r.closed]
    assert len(circle) == 1                               # the playlot ring only
    assert abs(circle[0].length_pt - perim) < 1.0         # shape correct, flagged


def test_curve_run_measured(tmp_path):
    # Guard: the fixture also draws a curved run — streak of lead-in line plus
    # a cubic Bezier. Truth is the SAMPLED polyline, not the true curve:
    # 8-segment chord sampling cannot hit rel 1e-6 of a true cubic. The
    # fixture records ground_truth["curve_run_pt"] = the length its own
    # sampler produces; this test asserts extraction + sampling are
    # consistent with that sampler within 1e-6.
    pdf, truth = make_synthetic_drawing(tmp_path)
    sheet = extract_sheet(pdf)
    runs = runs_from_strokes(sheet)
    assert len(runs) >= 2                                 # pipe + curved run
    # NOTE-for-controller: the fixture (task 2) draws the curved run as a
    # 100.0 pt lead-in line (300,470)->(400,470) plus the Bezier, and records
    # curve_run_pt = bezier-only sampled length. The extracted chain is the
    # WHOLE stroke (lead-in end == bezier start, so they union into one chain),
    # so its length is curve_run_pt + 100.0. Compare the bezier portion.
    curved = [
        r for r in runs
        if abs((r.length_pt - 100.0) - truth["curve_run_pt"]) < 1e-6
    ]
    assert curved, (
        f"sampled curve not consistent with fixture sampler; "
        f"runs={[r.length_pt for r in runs]}, truth={truth['curve_run_pt']}"
    )
