"""Cross-check measured run lengths against dimension callouts on the sheet.

Trust-but-verify: contractors/engineers print dimension callouts next to the
linework they drew. If the engine's measured length of a run disagrees with
the callout in the same spot by more than 3%, either the scale, the
extraction, or the callout itself is wrong — a human should look.
"""
import re

from shapely.geometry import LineString, Point
from .models import TakeoffResult

# Why 12 pt, not the 6 pt in the brief's reconcile_runs comment: the fixture's
# own "24.0 m" callout sits 11.1 pt above the water-pipe linework, and the
# brief's dimension_callouts docstring names the window "12pt" — a 6 pt gate
# would exclude the one callout the fixture exists to exercise and the layer
# would never verify anything it can see. (ponytail: one constant; flip if a
# denser-sheet review wants it tighter.)
WINDOW_PT = 12.0
TOLERANCE = 0.03

_NUM_M_RE = re.compile(r"\b(\d+(?:\.\d+)?)\s*(?:M\b|M\s*$)")


def dimension_callouts(words: list) -> list[tuple[float, tuple]]:
    """Return [(value_m, bbox)] for every dimension-callout candidate.

    Two patterns:
    (1) a number with a unit suffix "M" (on the whole-page uppercase text, the
        brief's regex — "24.0 m" extracts as TWO fitz words, so per-word
        matching would miss it): value in metres.
    (2) a word of 3-5 bare digits — unitless mm on JKR drawings: mm/1000 = m.
        Kept as a candidate here; the near-run gating happens in
        reconcile_runs (bare numbers in schedules are everywhere).
    """
    words = list(words)
    out: list[tuple[float, tuple]] = []

    texts = [w[4].upper() for w in words]     # (1): the M-suffixed pattern
    joined = " ".join(texts)
    offsets, i = [], 0
    for t in texts:
        offsets.append(i)
        i += len(t) + 1
    for m in _NUM_M_RE.finditer(joined):
        s = m.start(1)
        word = next((words[k] for k, t in enumerate(texts)
                     if offsets[k] <= s < offsets[k] + len(t)), None)
        if word is not None:
            out.append((float(m.group(1)), word[0:4]))

    for w in words:                            # (2): unitless mm
        t = w[4]
        if t.isascii() and t.isdigit() and 3 <= len(t) <= 5:
            out.append((int(t) / 1000.0, w[0:4]))
    return out


def reconcile_runs(result: TakeoffResult, words: list, runs: list) -> list[str]:
    """Compare each length measurement with the callout nearest its run
    linework (center-to-LINE distance via shapely, so leader arrows and label
    space of OTHER runs don't pull in foreign dimensions). Match within 3% ->
    no line; mismatch > 3% -> "<CLASS>: drawing says X.XX m — engine measured
    Y.Y m — REVIEW". Returns the QA lines (possibly empty)."""
    lines: list[str] = []
    runs_by_id = {r.id: r for r in runs}
    callouts = dimension_callouts(words)
    for meas in result.measurements:
        if meas.measure != "length" or meas.unit != "m":
            continue
        near: list[tuple[float, float]] = []   # (dist, value)
        for cid in meas.source_ids:
            run = runs_by_id.get(cid)
            if run is None or len(run.points) < 2:
                continue
            line = LineString(run.points)
            for val, bbox in callouts:
                cx = (bbox[0] + bbox[2]) / 2.0
                cy = (bbox[1] + bbox[3]) / 2.0
                d = line.distance(Point(cx, cy))
                if d <= WINDOW_PT:
                    near.append((d, val))
        if not near or meas.quantity == 0:
            continue
        _d, callout = min(near)
        if abs(callout - meas.quantity) / meas.quantity > TOLERANCE:
            lines.append(
                f"{meas.class_name_en.upper()}: drawing says {callout:.2f} m — "
                f"engine measured {meas.quantity:.1f} m — REVIEW"
            )
    return lines
