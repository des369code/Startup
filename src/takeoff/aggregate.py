"""Multi-sheet per-trade aggregation — the wedge demo deliverable.

``aggregate()`` runs ``measure()`` over every sheet then ``merge_rollups()``
sums quantities per (class_name_en, measure, unit) across sheets.

CRITICAL honesty constraint: ``reconciled`` is ALWAYS False here. Cross-sheet
dedup — the same room drawn on plan AND section must be counted once — is
deferred to the reconciliation phase (app plan), so a raw sum must never be
mistaken for a deduped bill of quantities.
"""
from dataclasses import dataclass

from .measure import measure
from .models import TakeoffResult
from .semantics import SemanticsClient


@dataclass
class TradeRollup:
    class_name_en: str
    measure: str           # "area" | "length" | "count"
    total: float           # sum across sheets
    unit: str
    per_sheet: list[tuple[str, float]]   # (sheet name, quantity) — traceability
    reconciled: bool       # always False in v0 — dedupe is deferred


def merge_rollups(results: list[TakeoffResult]) -> list[TradeRollup]:
    """Sum quantities per (class_name_en, measure, unit) across sheets.

    Rollup key is the readable triple, NOT class_id: per-sheet/per-tile ids
    collide (H2, same rule as the tile merge), so an id-key would split one
    trade into rows. per_sheet accumulates by sheet name (a repeated key on
    one sheet just adds into that sheet's entry). Sorted deterministic.
    """
    buckets: dict[tuple[str, str, str], dict] = {}
    for r in results:
        for m in r.measurements:
            key = (m.class_name_en, m.measure, m.unit)
            b = buckets.setdefault(key, {"total": 0.0, "per_sheet": {}})
            b["total"] += m.quantity
            b["per_sheet"][r.sheet_name] = (
                b["per_sheet"].get(r.sheet_name, 0.0) + m.quantity)
    return [
        TradeRollup(
            class_name_en=key[0], measure=key[1], total=b["total"],
            unit=key[2], per_sheet=sorted(b["per_sheet"].items()),
            reconciled=False,
        )
        for key, b in sorted(buckets.items())
    ]


def aggregate(files: list[str], semantics: SemanticsClient,
              scale_override: int | None = None) -> list[TradeRollup]:
    """Run measure() per file, then roll up per trade across the sheets.

    semantics is REQUIRED (no client default): a forgotten arg must fail at the
    call site, not silently spawn an API-money-burning Claude client."""
    results = [measure(f, semantics=semantics, scale_override=scale_override).result
               for f in files]
    return merge_rollups(results)
