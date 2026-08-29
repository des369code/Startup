"""Benchmark harness — the product's honesty gate.

Modes (see benchmarks/README.md):
  (no flags)          math pass: measure() + FakeSemantics on the v1+v2
                      synthetic fixtures; every quantity judged EXACTLY
                      (areas/lengths rel 1e-6, counts exact). Exit 0 iff all
                      rows PASS. No API calls.
  --live              the same two fixtures through the REAL
                      ClaudeSemanticsClient (billable; needs ANTHROPIC_API_KEY
                      or `ant auth login`). Rows carry the mandatory
                      classification column (recall=/misassign= — computable
                      because the fixtures know ground truth). Tolerances:
                      quantity ±1 m² / ±0.5 m, recall >= 0.9, misassign = 0.
                      Exit 0 iff all rows PASS.
  --real --truth      the corpus acceptance gate: one real JKR sheet measured
                      with Claude vs a ground-truth BoQ CSV, plus a GATE
                      verdict line (see benchmarks/README.md). Exit 0 iff the
                      gate is READY.

Honesty contract (README "Accuracy honesty"): the math pass proves the
engine's arithmetic on synthetic truth. Real-JKR accuracy is UNKNOWN until
the corpus gate runs — this script IS that gate. No "we'll check later":
row or ticket, always (plan Task 13).
"""
import argparse
import contextlib
import csv
import io
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
with contextlib.redirect_stdout(io.StringIO()):
    # pymupdf's `fitz` shim prints a deprecation warning to stdout at import
    # (see src/takeoff/cli.py); the benchmark's stdout is the table. Also put
    # src/ FIRST: this venv ships a non-editable installed copy (task 12's
    # .pth quirk) that can lag the repo — the benchmark must measure the code
    # pytest tests, which runs against src/.
    sys.path.insert(0, str(ROOT / "src"))
    sys.path.insert(0, str(ROOT))
    from takeoff.measure import measure
    from takeoff.semantics import ClaudeSemanticsClient
    from takeoff.testing import FakeSemantics
    from tests.fixtures import (
        make_synthetic_drawing, make_synthetic_drawing_v2, world_to_pt,
    )

REL_TOL = 1e-6            # math pass: relative tolerance (areas/lengths)
QTY_TOL = {"area": 1.0, "length": 0.5}   # live/real: absolute ± m² / ± m
RECALL_MIN = 0.9          # live: recall floor
IGNORE = "<ignore>"       # fixture truth for deliberately-unmeasured candidates

FIXTURES = [
    ("v1-synthetic", make_synthetic_drawing),
    ("v2-synthetic", make_synthetic_drawing_v2),
]


@dataclass
class Row:
    sheet: str
    name: str             # class name (truth class and/or measured class)
    kind: str             # "area" | "length" | "count"
    truth: float | None   # world-unit truth (None: no truth / not measured)
    value: float | None   # measured world-unit quantity
    unit: str | None      # measured unit
    ok: bool
    recall: float | None = None
    misassign: int | None = None


# ---------------------------------------------------------------- expectations

def _expected(kind: str, truth: dict) -> list[tuple[str, str, float]]:
    """World-unit ground truth per sheet kind: (class, measure, value)."""
    if kind == "v2-synthetic":
        return [("Asphalt", "area", truth["areas"]["asphalt"]),
                ("Planting", "area", truth["areas"]["planting"]),
                ("Paving", "area", truth["areas"]["paving"]),
                ("Manhole", "count", float(truth["counts"]["manhole"]))]
    return [("Asphalt", "area", truth["areas"]["asphalt"]),
            ("Planting", "area", truth["areas"]["planting"]),
            ("Playlot", "area", truth["polygonize_area"]),
            ("Water Pipe", "length", truth["runs"]["water_pipe"]),
            # the curve's fixture oracle is sampled in pt; convert with the
            # sheet's own pt-per-metre (v1's 1:100 scale)
            ("Curve", "length",
             truth["curve_chain_run_pt"] / world_to_pt(1, 100)),
            ("Manhole", "count", float(truth["counts"]["manhole"]))]


def _truth_allocation(outcome, kind: str) -> dict[str, str]:
    """Per-candidate ground truth (candidate id -> class name, or IGNORE).

    Same index rules FakeSemantics scripts, taken from the fixture design, so
    live recall/misassignment are computable: the fixture KNOWS its geometry.
    """
    fills = [c for c in outcome.regions if c.source == "fill"]
    polys = [c for c in outcome.regions if c.source == "polygonize"]
    alloc: dict[str, str] = {}
    if kind == "v2-synthetic":
        for cls, c in zip(("Asphalt", "Planting", "Paving"), fills):
            alloc[c.id] = cls
        for a in outcome.anchors:
            alloc[a.id] = "Manhole"
    else:
        alloc[fills[0].id] = "Asphalt"
        alloc[fills[1].id] = "Planting"
        alloc[polys[0].id] = "Playlot"
        alloc[polys[1].id] = IGNORE  # legend box: a ring, but not a measure
        if outcome.runs:
            alloc[outcome.runs[0].id] = "Water Pipe"
        if len(outcome.runs) > 1:
            alloc[outcome.runs[1].id] = "Curve"
        for a in outcome.anchors:
            alloc[a.id] = "Manhole"
    return alloc


# ------------------------------------------------------------------- judging

def _math_close(truth: float, value: float, kind: str) -> bool:
    if kind == "count":
        return value == truth
    if truth == 0:
        return value == 0
    return abs(value - truth) <= REL_TOL * abs(truth)


def _live_close(truth: float, value: float, kind: str) -> bool:
    if kind == "count":
        return value == truth
    return abs(value - truth) <= QTY_TOL[kind]


def _math_rows(kind: str, outcome, expected) -> list[Row]:
    by_name = {m.class_name_en: m for m in outcome.result.measurements}
    exp_names = [e[0] for e in expected]
    names = exp_names + [n for n in by_name if n not in exp_names]
    rows = []
    for name in names:
        exp = next((e for e in expected if e[0] == name), None)
        m = by_name.get(name)
        if exp is None:  # measured class with no fixture truth: product drift
            rows.append(Row(sheet=kind, name=name, kind=m.measure, truth=None,
                            value=m.quantity, unit=m.unit, ok=False))
            continue
        if m is None:  # truth class with no measurement
            rows.append(Row(sheet=kind, name=name, kind=exp[1],
                            truth=exp[2], value=None, unit=None, ok=False))
            continue
        unit = {"area": "m2", "length": "m", "count": "pcs"}[exp[1]]
        ok = (m.unit == unit and _math_close(exp[2], m.quantity, exp[1]))
        rows.append(Row(sheet=kind, name=name, kind=exp[1], truth=exp[2],
                        value=m.quantity, unit=m.unit, ok=ok))
    return rows


def _live_rows(kind: str, outcome, expected, alloc: dict) -> list[Row]:
    by_name = {m.class_name_en: m for m in outcome.result.measurements}
    exp_names = [e[0] for e in expected]
    names = exp_names + [n for n in by_name if n not in exp_names]
    rows = []
    for name in names:
        exp = next((e for e in expected if e[0] == name), None)
        m = by_name.get(name)
        e_kind = exp[1] if exp else (m.measure if m else None)
        truth_ids = {cid for cid, c in alloc.items() if c == name}
        assigned = set(m.source_ids) if m else set()
        recall = None if not truth_ids else len(assigned & truth_ids) / len(truth_ids)
        misassign = len(assigned - truth_ids)
        r = Row(sheet=kind, name=name, kind=e_kind,
                truth=exp[2] if exp else None,
                value=m.quantity if m else None,
                unit=m.unit if m else None, ok=False,
                recall=recall, misassign=misassign)
        qty_ok = (True if r.truth is None or r.value is None
                  else _live_close(r.truth, r.value, r.kind))
        cls_ok = (r.recall is None and r.misassign == 0
                  or r.recall is not None and r.recall >= RECALL_MIN
                  and r.misassign == 0)
        r.ok = qty_ok and cls_ok
        rows.append(r)
    return rows


# ------------------------------------------------------------------ printing

def _fmt(v: float | None) -> str:
    return "-" if v is None else f"{v:.2f}"


def _fmt_delta(d: float | None) -> str:
    if d is None or abs(d) < 0.0005:  # sub-0.001 deltas print as exact: no -0.000
        return "0.000"
    return f"{d:+.3f}"


def _print_rows(rows: list[Row], classification: bool = False) -> None:
    header = (["sheet", "class", "measure", "truth", "measured", "delta"]
              + (["classification"] if classification else []) + ["PASS/FAIL"])
    table = [[
        r.sheet, r.name, r.kind, _fmt(r.truth), _fmt(r.value),
        (_fmt_delta(r.value - r.truth)
         if r.truth is not None and r.value is not None else "-"),
    ] for r in rows]
    if classification:
        for i, r in enumerate(rows):
            if r.recall is None:
                table[i].append(f"recall=n/a misassign={r.misassign}")
            else:
                table[i].append(f"recall={r.recall:.2f} misassign={r.misassign}")
    for i, r in enumerate(rows):
        table[i].append("PASS" if r.ok else "FAIL")
    all_rows = [header, *table]
    widths = [max(len(row[i]) for row in all_rows) for i in range(len(header))]
    for row in all_rows:
        print("  ".join(row[i].ljust(widths[i])
                        for i in range(len(header))).rstrip())


# ------------------------------------------------------------------ the modes

def _math_pass() -> int:
    all_rows = []
    for kind, maker in FIXTURES:
        with tempfile.TemporaryDirectory() as d:
            pdf, truth = maker(Path(d))
            outcome = measure(pdf, semantics=FakeSemantics())
        all_rows += _math_rows(kind, outcome, _expected(kind, truth))
    _print_rows(all_rows)
    ok = sum(1 for r in all_rows if r.ok)
    print(f"math pass: {ok}/{len(all_rows)} rows PASS "
          f"(rel 1e-6 areas/lengths, exact counts)")
    return 0 if ok == len(all_rows) else 1


def _live_semantics() -> ClaudeSemanticsClient:
    try:
        return ClaudeSemanticsClient()
    except Exception as e:
        print(f"live semantics unavailable: {e} "
              f"(set ANTHROPIC_API_KEY or run `ant auth login`)", file=sys.stderr)
        raise SystemExit(2) from e


def _live_pass() -> int:
    print("LIVE SEMANTICS — real Claude calls on the synthetic fixtures "
          "(billable; requires ANTHROPIC_API_KEY or `ant auth login`)")
    semantics = _live_semantics()
    all_rows = []
    for kind, maker in FIXTURES:
        with tempfile.TemporaryDirectory() as d:
            pdf, truth = maker(Path(d))
            outcome = measure(pdf, semantics=semantics)
        all_rows += _live_rows(kind, outcome, _expected(kind, truth),
                               _truth_allocation(outcome, kind))
    _print_rows(all_rows, classification=True)
    ok = sum(1 for r in all_rows if r.ok)
    print(f"live: {ok}/{len(all_rows)} rows PASS "
          f"(qty ±1 m2 / ±0.5 m, recall >= {RECALL_MIN}, misassign 0)")
    return 0 if ok == len(all_rows) else 1


def _read_boq(path: str) -> dict[str, tuple[float, str]]:
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows or not {"class", "quantity", "unit"} <= set(rows[0]):
        raise ValueError(f"{path}: BoQ CSV header must contain "
                         f"class,quantity,unit (got {sorted(rows[0]) if rows else 'nothing'})")
    out: dict[str, tuple[float, str]] = {}
    for r in rows:
        name = r["class"].strip()
        unit = r["unit"].strip().lower()
        if name in out:
            raise ValueError(f"{path}: duplicate class {name!r}")
        if unit not in ("m2", "m", "pcs"):
            raise ValueError(f"{path}: unit {unit!r} not in m2|m|pcs")
        out[name] = (float(r["quantity"]), unit)
    return out


def _read_triage(path: str) -> dict[str, tuple[str, str]]:
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows or not {"class", "label", "ticket"} <= set(rows[0]):
        raise ValueError(f"{path}: triage CSV header must contain "
                         f"class,label,ticket (got {sorted(rows[0]) if rows else 'nothing'})")
    out: dict[str, tuple[str, str]] = {}
    for r in rows:
        out[r["class"].strip()] = (r["label"].strip().lower(), r["ticket"].strip())
    return out


def _gate_verdict(fails: list[str], triage: dict) -> tuple[bool, list[str]]:
    """(ready, untriaged) — READY when no row fails, or EVERY failing row is
    triaged (label `fix task`/`known gap` + non-empty ticket). Row or ticket,
    always: no magic "later" (plan Task 13 corpus acceptance)."""
    triaged = {n for n in fails
               if n in triage and triage[n][1]
               and triage[n][0] in ("known gap", "fix task")}
    untriaged = [n for n in fails if n not in triaged]
    return (not fails or not untriaged), untriaged


def _real_rows(sheet: str, result, boq: dict) -> list[Row]:
    by_name = {m.class_name_en: m for m in result.measurements}
    names = list(boq) + [n for n in by_name if n not in boq]
    rows = []
    for name in names:
        t = boq.get(name)
        m = by_name.get(name)
        kind = {"m2": "area", "m": "length", "pcs": "count"}[t[1]] if t else (
            m.measure if m else None)
        r = Row(sheet=sheet, name=name, kind=kind,
                truth=t[0] if t else None,
                value=m.quantity if m else None,
                unit=m.unit if m else None, ok=False)
        if t is not None and m is not None:
            r.ok = (_live_close(t[0], m.quantity, kind) and m.unit == t[1])
        rows.append(r)
    return rows


def _real_gate(pdf: str, truth_csv: str, triage_csv: str | None) -> int:
    print("REAL SEMANTICS — live Claude calls on a real sheet (billable; "
          "drawings leave the machine during measurement: Anthropic API, "
          "PDPA 2010 declaration in the app plan)")
    # validate the inputs BEFORE any API call: a typo'd CSV must not bill
    try:
        boq = _read_boq(truth_csv)
        triage = _read_triage(triage_csv) if triage_csv else {}
    except ValueError as e:
        print(e, file=sys.stderr)
        return 2
    semantics = _live_semantics()
    try:
        outcome = measure(pdf, semantics=semantics)
    except Exception as e:
        print(f"measure failed on {pdf}: {e}", file=sys.stderr)
        return 2
    rows = _real_rows(Path(pdf).stem, outcome.result, boq)
    # A BoQ holds quantity truth, not candidate truth: recall/misassign
    # columns are n/a for real sheets (the fixture-only metrics).
    _print_rows(rows)
    fails = [r.name for r in rows if not r.ok]
    ready, untriaged = _gate_verdict(fails, triage)
    if not fails:
        print(f"GATE: READY — all {len(rows)} rows pass per-class metrics on "
              f"{Path(pdf).name} (corpus-gate acceptance: one real JKR sheet)")
        return 0
    if ready:
        print(f"GATE: READY — {len(fails)} failing rows; every one triaged in "
              f"{triage_csv} (fix task or `known gap` + ticket) "
              f"(corpus-gate acceptance: full triage)")
        return 0
    print(f"GATE: NOT READY — {len(fails)} failing rows "
          f"({', '.join(fails)}), {len(untriaged)} un-triaged "
          f"({', '.join(untriaged)}). Every failing row needs a fix task or a "
          f"`known gap` label + ticket: add them to a triage CSV "
          f"(class,label,ticket) and pass --triage. Row or ticket, always — "
          f"no magic 'later'.")
    return 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="benchmarks/run_benchmark.py",
        description="Takeoff benchmark harness: math pass on the synthetic "
                    "fixtures (no API), --live (real Claude, billable), or "
                    "--real --truth (corpus acceptance gate).",
    )
    p.add_argument("--live", action="store_true",
                   help="run the synthetic fixtures through the real Claude "
                        "semantics client (billable; needs ANTHROPIC_API_KEY "
                        "or `ant auth login`)")
    p.add_argument("--real", metavar="PDF",
                   help="corpus acceptance gate: real JKR sheet PDF")
    p.add_argument("--truth", metavar="CSV",
                   help="ground-truth BoQ CSV for --real (header: "
                        "class,quantity,unit; unit m2|m|pcs)")
    p.add_argument("--triage", metavar="CSV",
                   help="optional triage record for --real (header: "
                        "class,label,ticket; label in {fix task, known gap})")
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.real:
        if not args.truth:
            parser.error("--real requires --truth <boq.csv>")
        return _real_gate(args.real, args.truth, args.triage)
    if args.live:
        return _live_pass()
    return _math_pass()


if __name__ == "__main__":
    sys.exit(main())
