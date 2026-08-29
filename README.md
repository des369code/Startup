# takeoff

Quantity takeoff from born-digital construction drawing PDFs (JKR/MDB style):
measured quantities (m² / m / pcs) plus an annotated PDF and Excel/JSON
output. Claude assigns meaning — which candidate is asphalt, water pipe,
manhole; the engine computes every number in code.

## Install

```sh
pip install -e ".[dev]"
ant auth login        # or: export ANTHROPIC_API_KEY=sk-...
```

macOS note: if the `takeoff` console script errors, `uv install .` works too.

## Quickstart

```sh
takeoff run drawing.pdf --prompt "asphalt"
```

Measures one sheet (or every `*.pdf` in a directory, with a per-trade
rollup), writes `<sheet>-takeoff.xlsx`, `<sheet>-annotated.pdf`,
`<sheet>-qa.json` into `./out`. `takeoff --help` / `takeoff run --help` list
the flags (`--scale N`, `--out DIR`, `--dry-run`, `--mock`).

No API key handy? `--mock` runs the exact same pipeline with scripted
semantics — no calls, deterministic output. On the synthetic fixture it
prints exactly:

```
MOCK SEMANTICS — no API calls, results are scripted
class       measure  quantity  unit
Asphalt     area     50.00     m2
Planting    area     64.00     m2
Playlot     area     36.00     m2
Water Pipe  length   24.00     m
Curve       length   9.85      m
Manhole     count    2.00      pcs
qa: not measured: 1 candidates ignored by semantics — human review
```

## The QA gate

The annotated PDF is what a human reviews: class overlays on every measured
candidate, and a mark on every candidate the engine did not measure — you see
exactly what was skipped, in place. The "not measured" list in the summary
(`qa: not measured: …` lines) is the report: nothing is dropped silently.
Ignored or unclassified candidates are reported, never measured as wrong
numbers. Other QA flags are plain English — scale ambiguity, mixed class
evidence, conflicting class maps, prompt terms not in the legend. A REVIEW
line means the drawing's own dimension callout disagrees with the engine's
measurement of that run: read the callout in the annotation and don't trust
either number blindly.

## Tests

```sh
pytest tests/ -m "not live"
```

The one `live`-marked test calls Claude for real and needs a key
(ANTHROPIC_API_KEY or `ant auth login`).

## Known ceilings (v0 honesty)

- Vector fills + stroke rings only. Raster imprints and unclosed loose
  strokes are NOT candidates: they land in the QA report as "not measured —
  human review", never as wrong numbers.
- Scanned/handwritten sheets + OCR: later. Volumes/TIN earthworks: later.
  SMM2 measurement scope rules (kerb single- vs both-side, net vs gross):
  later — the local wedge, being tracked.
- Stroke-chain edge cases not covered by the fixtures: forks (walk takes the
  first unvisited edge), lollipop cycles with tails, figure-eights, double-
  drawn duplicate edges. A lollipop could leak a perimeter-length run on a
  real sheet; the corpus track will add fixture shapes.
- Cross-sheet totals are NOT_RECONCILED: the same element drawn twice counts
  twice (dedupe is app-plan, flagged in the output).
- PDF only. Drawings leave the machine during measurement (Anthropic API;
  PDPA 2010 data declaration lives in the app plan).
- 400-candidate cap per sheet; overflow is listed in the QA report.

## Accuracy honesty

Synthetic truth is exact: the benchmark math pass
(`.venv/bin/python benchmarks/run_benchmark.py`) recovers the fixture ground
truth to rel 1e-6 (areas/lengths) with exact counts. REAL JKR accuracy is
UNKNOWN until the corpus exists — contact the QS contacts, collect drawings +
ground-truth BoQs (spec §6). The benchmark's `--live --real` gate is the
measurement harness, and the ≥97% / ±3% target (spec §1.4) is tracked there,
not here. See `benchmarks/README.md` for the three modes and the corpus-gate
acceptance criteria.

## Corpus open item

Corpus owner: founder — the data track (real JKR sheets + ground-truth BoQs),
not a code task. This repo's gate is ready; the data is the dependency.
