"""Annotated PDF (human QA surface) tests.

annotate_pdf is the audit artifact: class-coloured overlays show WHERE each
measured quantity came from, quantity labels carry the number, and an X
marks candidates no measurement counted. Ground truth fixtures only; no LLM.
"""
from dataclasses import replace

import fitz

from takeoff.annotate import annotate_pdf
from takeoff.measure import measure
from takeoff.testing import FakeSemantics
from tests.fixtures import make_synthetic_drawing


def _annotate(tmp_path, name="annotated.pdf", *, drop_class=None):
    """Fixture -> measure(FakeSemantics) -> annotate. Optionally drop one
    measurement so its candidates become unmeasured (X-out path)."""
    pdf, _ = make_synthetic_drawing(tmp_path)
    outcome = measure(pdf, semantics=FakeSemantics())
    result = outcome.result
    if drop_class is not None:
        result = replace(
            result,
            measurements=[m for m in result.measurements
                          if m.class_name_en != drop_class],
        )
    out = annotate_pdf(pdf, result, outcome.regions, outcome.runs,
                       str(tmp_path / name), outcome.anchors)
    return out, pdf


def test_annotated_pdf_exists(tmp_path):
    out, _ = _annotate(tmp_path)
    ann = fitz.open(out)
    assert ann.page_count == 1
    ann.close()


def test_annotated_pdf_has_quantity_label(tmp_path):
    out, _ = _annotate(tmp_path)
    assert any("50.00" in page.get_text() for page in fitz.open(out))


def test_annotated_pdf_x_marks_unmeasured(tmp_path):
    # every candidate is measured on the synthetic fixture -> no X marks
    out, _ = _annotate(tmp_path)
    assert "X" not in fitz.open(out)[0].get_text()

    # drop Playlot: its polygonize candidates become uncovered -> X-drawn once
    # per unmeasured candidate. Assert BOTH the text X and the vector overlay
    # (dashed grey outline) — the overlay is what sits on the shape layer and
    # would silently vanish if the Shape items were never committed.
    xout, _ = _annotate(tmp_path, name="xout.pdf", drop_class="Playlot")
    page = fitz.open(xout)[0]
    assert "X" in page.get_text()
    grey_dashed = [d for d in page.get_drawings()
                   if d.get("color") and d["color"][1] == 0.5 and d.get("dashes")]
    assert len(grey_dashed) >= 2  # ring + legend box both unmeasured now
