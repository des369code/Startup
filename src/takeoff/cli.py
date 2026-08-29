"""The takeoff CLI — the only human entry point in v0.

``takeoff run <pdf>`` measures one vector sheet and writes
``<sheet>-takeoff.xlsx``, ``<sheet>-annotated.pdf``, ``<sheet>-qa.json`` into
``--out``. ``--mock`` swaps in the scripted FakeSemantics (no API spend);
``--dry-run`` prints a per-sheet cost estimate from geometry alone (no
semantics, no files).
"""
import argparse
import contextlib
import io
import sys
import traceback
from pathlib import Path

with contextlib.redirect_stdout(io.StringIO()):
    # pymupdf's `fitz` shim prints a deprecation warning straight to stdout at
    # import. The CLI's stdout IS the product output (README pastes it
    # verbatim), so keep the entry point clean — suppress once here, not in
    # every module that imports fitz.
    from .annotate import annotate_pdf
    from .geometry_regions import regions_from_fills, regions_from_polygonize
    from .geometry_runs import runs_from_strokes
    from .measure import _dedupe_regions, measure
    from .pdf_extract import extract_sheet, page_text_upper
    from .reconcile import reconcile_runs
    from .report import to_json, write_xlsx
    from .scale import apply_override, parse_scale
    from .semantics import ClaudeSemanticsClient, anchor_candidates
    from .testing import FakeSemantics

MOCK_BANNER = "MOCK SEMANTICS — no API calls, results are scripted"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="takeoff",
        description="Quantity takeoff from vector construction drawings "
                    "(JKR/MDB style). Run 'takeoff run -h' for the flag "
                    "reference.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser(
        "run",
        help="measure one sheet and write xlsx + annotated PDF + qa.json",
        description="Measure one sheet: extract vector geometry, classify every "
                    "candidate via Claude semantics, compute quantities in code "
                    "(m2 / m / pcs), write the deliverable files. For a first "
                    "non-mock run, set ANTHROPIC_API_KEY first.",
    )
    run.add_argument("pdf", help="path to the drawing PDF (single vector sheet)")
    run.add_argument(
        "--prompt", default="", metavar="TEXT",
        help='classes to measure, e.g. "asphalt" — empty (default) means every '
             "class the legend declares",
    )
    run.add_argument(
        "--scale", type=int, default=None, metavar="N",
        help="scale factor override, e.g. 250 for a 1:250 sheet; when omitted "
             "the title-block scale text is parsed and Claude's reading is "
             "cross-checked",
    )
    run.add_argument(
        "--out", default="./out", metavar="DIR",
        help="output directory for <sheet>-takeoff.xlsx, "
             "<sheet>-annotated.pdf and <sheet>-qa.json (created if missing; "
             "default ./out)",
    )
    run.add_argument(
        "--mock", action="store_true",
        help="scripted semantics instead of Claude — no API calls, results are "
             "deterministic; for demos and tests",
    )
    run.add_argument(
        "--dry-run", action="store_true",
        help="print a per-sheet cost estimate from geometry alone (extract + "
             "candidates + scale) — no API calls, no files written",
    )
    return parser


def _observe(outcome) -> None:
    """One structured stderr line per sheet — the 'why did it miss rooms' signal.

    counts: candidate sources as actually measured (post-dedupe, post-overflow
    truncation); classes = measurements emitted (legend classes with candidates
    in scope)."""
    fills = sum(1 for c in outcome.regions if c.source == "fill")
    polygonize = len(outcome.regions) - fills
    print(f"takeoff: sheet={outcome.result.sheet_name} fills={fills} "
          f"polygonize={polygonize} runs={len(outcome.runs)} "
          f"anchors={len(outcome.anchors)} "
          f"classes={len(outcome.result.measurements)} "
          f"capped={'yes' if outcome.result.overflowed else 'no'}",
          file=sys.stderr)


def _print_summary(result, review_lines: list[str]) -> None:
    header = ("class", "measure", "quantity", "unit")
    rows = [(m.class_name_en, m.measure, f"{m.quantity:.2f}", m.unit)
            for m in result.measurements]
    table = [header, *rows]
    widths = [max(len(row[i]) for row in table) for i in range(4)]
    for row in table:
        print("  ".join(row[i].ljust(widths[i]) for i in range(4)).rstrip())
    for line in [*review_lines, *result.qa]:
        print(f"qa: {line}")


def _dry_run(pdf_path: str, scale_override: int | None) -> int:
    """Geometry-only prep, no semantics calls, no file writes. Exit code."""
    try:
        sheet = extract_sheet(pdf_path)
        regions = _dedupe_regions(
            regions_from_fills(sheet) + regions_from_polygonize(sheet))
        runs = runs_from_strokes(sheet)
        anchors = anchor_candidates(sheet)
        text = page_text_upper(sheet.words)
        if scale_override is not None:  # parsed for estimate realism (same as run)
            apply_override(text, scale_override)
        else:
            parse_scale(text)
    except Exception as e:
        print(f"cannot read PDF: {e}", file=sys.stderr)
        return 1
    n = len(regions) + len(runs) + len(anchors)
    # ponytail: the roughest number in the product — 1 call per sheet until
    # >100 candidates, then the fixed 2x2 tile plan (4 calls). Ignores
    # measure()'s zero-candidate short-circuit and empty-tile skipping, so
    # treat it as an upper bound. Refine when real usage exists.
    calls = 1 if n <= 100 else 4
    print(f"dry run: {n} candidates, {calls} semantic calls, "
          f"est. 16k tokens/call → approx $0.50–2.00/sheet at claude-opus-5 rates")
    return 0


def _run(args) -> int:
    if args.mock:
        print(MOCK_BANNER)
    if args.dry_run:
        return _dry_run(args.pdf, args.scale)

    semantics = FakeSemantics() if args.mock else ClaudeSemanticsClient()

    try:
        sheet = extract_sheet(args.pdf)
    except Exception as e:
        print(f"cannot read PDF: {e}", file=sys.stderr)
        return 1

    try:
        outcome = measure(args.pdf, args.prompt, semantics=semantics,
                          scale_override=args.scale)
        review_lines = reconcile_runs(outcome.result, sheet.words, outcome.runs)
    except ValueError as e:
        # measure()'s own PDF-level errors (encrypted sheet, bad file) exit with
        # the same user-facing shape as an extract failure.
        print(f"cannot read PDF: {e}", file=sys.stderr)
        return 1
    except Exception:
        traceback.print_exc()
        return 1

    _observe(outcome)
    _print_summary(outcome.result, review_lines)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    stem = Path(args.pdf).stem
    try:
        write_xlsx(outcome.result, str(out / f"{stem}-takeoff.xlsx"))
        annotate_pdf(args.pdf, outcome.result, outcome.regions, outcome.runs,
                     str(out / f"{stem}-annotated.pdf"), outcome.anchors)
        (out / f"{stem}-qa.json").write_text(to_json(outcome.result))
    except Exception:
        traceback.print_exc()
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return _run(args) if args.command == "run" else 2


if __name__ == "__main__":
    sys.exit(main())
