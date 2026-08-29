"""Human QA surface: the annotated PDF.

The annotated artifact IS the audit trail: class-coloured overlays show WHERE
each measured quantity came from, a quantity label sits at the candidate
centroid, and candidates no measurement counted (unclassified or ignored by
semantics) get a thin dashed-grey outline with an X at their centroid.
Coordinates are PDF points on page 0, matching extraction.

PyMuPDF >=1.28 Shape API: draw_* calls take geometry only; all styling
(color/fill/width/dashes/opacity) is applied per Shape via finish().
"""
import fitz

from .models import Anchor, CandidateRegion, CandidateRun, TakeoffResult
from .semantics import _centroid

# Fixed palette keyed by class id; classes beyond the table cycle around.
# (measure() renumbers classes C1..Cn, so cycling by numeric suffix == modulo.)
_PALETTE = {
    "C1": (1.0, 0.55, 0.0),    # orange
    "C2": (0.05, 0.6, 0.2),    # green
    "C3": (0.15, 0.35, 0.9),   # blue
    "C4": (0.8, 0.1, 0.3),     # crimson
    "C5": (0.55, 0.2, 0.85),   # purple
    "C6": (0.0, 0.6, 0.65),    # teal
}
_GREY = (0.5, 0.5, 0.5)
_FILL_ALPHA = 0.35            # overlay fill opacity
_X_DASHES = "[1.5 2] 0"       # thin dashed-grey outline pattern


def _color_for(class_id: str) -> tuple:
    keys = list(_PALETTE)
    digits = "".join(ch for ch in class_id if ch.isdigit())
    idx = int(digits) - 1 if digits else len(keys)
    return _PALETTE[keys[idx % len(keys)]]


def annotate_pdf(pdf_path_in: str, result: TakeoffResult,
                 regions: list[CandidateRegion], runs: list[CandidateRun],
                 out_path: str, anchors: list[Anchor] | None = None) -> str:
    """Open a fresh copy of the drawing, overlay measurement and X-out marks,
    save the annotated PDF, and return ``out_path``."""
    anchors = anchors or []
    by_id = {c.id: c for c in (*regions, *runs, *anchors)}
    doc = fitz.open(pdf_path_in)
    try:
        page = doc[0]

        covered: set[str] = set()
        for m in result.measurements:
            color = _color_for(m.class_id)
            cands = [by_id[i] for i in m.source_ids if i in by_id]
            covered.update(c.id for c in cands)
            if not cands:
                continue

            rects = [c for c in cands if isinstance(c, CandidateRegion)]
            if rects:
                shape = page.new_shape()
                for c in rects:  # v0: region overlay = bbox rect, plan-sanctioned
                    shape.draw_rect(fitz.Rect(*c.bbox))
                shape.finish(color=color, fill=color, fill_opacity=_FILL_ALPHA,
                             stroke_opacity=0.9, width=1.0)
                shape.commit()  # finish() only sets styling; commit writes items

            polys = [c for c in cands if isinstance(c, CandidateRun)]
            if polys:
                shape = page.new_shape()
                for c in polys:
                    shape.draw_polyline(c.points)
                shape.finish(color=color, fill=None, width=1.5,
                             closePath=False, stroke_opacity=0.9)
                shape.commit()

            label = f"{m.class_name_en} {m.quantity:.2f} {m.unit}"
            # count classes: one label per counted anchor; area/length: one
            # label at the first candidate's centroid (one per class is fine).
            label_pts = ([_centroid(c) for c in cands]
                         if m.measure == "count" else [_centroid(cands[0])])
            for pt in label_pts:
                page.insert_text(pt, label, fontsize=7, color=color)

        # X-out: candidates (regions/runs/anchors) no measurement counted.
        for c in [c for c in (*regions, *runs, *anchors)
                  if c.id not in covered]:
            shape = page.new_shape()
            if isinstance(c, CandidateRun):
                shape.draw_polyline(c.points)
                style = {"fill": None, "closePath": False}
            else:
                shape.draw_rect(fitz.Rect(*c.bbox))
                style = {"fill": None}
            shape.finish(color=_GREY, width=0.8, dashes=_X_DASHES, **style)
            shape.commit()
            page.insert_text(_centroid(c), "X", fontsize=9, color=_GREY)

        doc.save(out_path)
    finally:
        doc.close()
    return out_path
