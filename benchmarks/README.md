# Benchmark harness

`benchmarks/run_benchmark.py` — the product's honesty gate. Three modes:

1. **Math pass** (no flags): `measure(...)` + `FakeSemantics` on the two
   synthetic fixtures (v1: 1:100, 2 areas + ring + runs + MH anchors; v2:
   1:200, 3 areas, 2-digit anchors). Every quantity judged against fixture
   ground truth: areas/lengths rel 1e-6, counts exact. Prints
   `sheet | class | measure | truth | measured | delta | PASS/FAIL`; exit 0
   iff all rows pass. No API calls. This proves the engine's arithmetic —
   nothing more, nothing less.
2. **`--live`**: the same two fixtures through the real Claude semantics
   client (billable; needs `ant auth login` or ANTHROPIC_API_KEY). Rows add
   the mandatory classification column `recall=<r> misassign=<m>`,
   computable because the fixtures know which candidate is what. Tolerances:
   quantity ±1 m² / ±0.5 m, recall ≥ 0.9, misassignment = 0. Quantity-only
   judgment is NOT accepted — classification decides.
3. **`--real <sheet.pdf> --truth <boq.csv> [--triage <csv>]`**: the corpus
   acceptance gate. One real JKR sheet measured with Claude vs ground truth.
   BoQ CSV header: `class,quantity,unit` (unit `m2|m|pcs`). Recall/misassign
   columns are n/a here: a BoQ holds quantity truth, not candidate truth.
   Quantity per-class metric = ±1 m² / ±0.5 m, counts exact. The script ends
   with a **GATE** verdict line:
   - READY when one real sheet passes per-class metrics, or
   - READY when every failing row is triaged: `--triage <csv>` with header
     `class,label,ticket`, label `fix task` or `known gap` + a ticket. Row or
     ticket, always — no "we'll check later".

**Adding a sheet to the corpus gate:** put the drawing PDF and its BoQ (QS
ground truth, per-class world-unit quantities) side by side, copy the BoQ to
the `class,quantity,unit` header shape, run mode 3, attach the GATE verdict
to the corpus run notes. If rows fail, either open a fix task (label the
triage row `fix task`) or label the row `known gap` + ticket.
`--real` validates the CSVs before any API call — a typo never bills.

**Evidence note:** spec §5 records the benchmark this harness independently
re-measures (Civils.ai 45/45 line items within ±5% vs Claude Sonnet 4.5 9/45
on a UK civils scheme — vendor-authored, directional); spec §6, open question
2, poses the Malaysian corpus question this gate is the instrument for.
Until real JKR sheets + BoQs land, synthetic exactness (mode 1) is the only
number this repo can honestly claim — see README "Accuracy honesty".
