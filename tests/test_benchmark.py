# tests/test_benchmark.py
"""The benchmark harness is part of the product contract: the math pass must
exit 0 when FakeSemantics + the engine recover the fixture ground truth.

This test runs the real script through subprocess (math pass only — no API),
exactly as a CI step or a human would: `.venv/bin/python benchmarks/run_benchmark.py`
from the repo root (task 13 brief + controller ruling).
"""
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "benchmarks"))
import run_benchmark  # noqa: E402  (benchmarks/ isn't a package; import by path)

from tests.fixtures import (  # noqa: E402
    make_synthetic_drawing,
    make_synthetic_drawing_v2,
)
from takeoff.measure import measure  # noqa: E402
from takeoff.testing import FakeSemantics  # noqa: E402


def test_benchmark_math_pass_exits_zero():
    proc = subprocess.run(
        [str(REPO_ROOT / ".venv" / "bin" / "python"),
         "benchmarks/run_benchmark.py"],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=30,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "PASS" in proc.stdout


def test_corpus_gate_verdict_triage_logic():
    """GATE verdict (plan acceptance a/b): no fails -> READY; every failing
    row triaged as `fix task`/`known gap` + ticket -> READY; a ticket-less or
    unlabelled row stays un-triaged -> NOT READY."""
    triage = {"Asphalt": ("known gap", "T-71"), "Paving": ("fix task", "T-72")}
    ready, untriaged = run_benchmark._gate_verdict([], triage)
    assert ready is True and untriaged == []
    ready, untriaged = run_benchmark._gate_verdict(["Asphalt", "Paving"], triage)
    assert ready is True and untriaged == []
    # ticket-less row is NOT triaged — row or ticket, always
    sloppy = {"Asphalt": ("known gap", "T-71"), "Paving": ("known gap", "")}
    ready, untriaged = run_benchmark._gate_verdict(["Asphalt", "Paving"], sloppy)
    assert ready is False and untriaged == ["Paving"]
    # wrong label is NOT triaged
    wrong = {"Asphalt": ("later", "T-99")}
    ready, untriaged = run_benchmark._gate_verdict(["Asphalt"], wrong)
    assert ready is False and untriaged == ["Asphalt"]


def test_live_classification_math_without_api(tmp_path):
    """The --live per-class metrics (recall/misassign) against the fixture
    truth allocation, exercised with FakeSemantics so no API call is made:
    a perfect semantics must produce recall=1.0, misassign=0, all rows PASS."""
    for kind, maker in (("v1-synthetic", make_synthetic_drawing),
                        ("v2-synthetic", make_synthetic_drawing_v2)):
        pdf, truth = maker(tmp_path)
        outcome = measure(pdf, semantics=FakeSemantics())
        rows = run_benchmark._live_rows(
            kind, outcome, run_benchmark._expected(kind, truth),
            run_benchmark._truth_allocation(outcome, kind))
        assert rows, kind
        assert all(r.ok for r in rows), kind
        assert all(r.recall == 1.0 and r.misassign == 0 for r in rows), kind
