"""The single orchestrator: extract PDF -> candidate regions/runs/anchors
-> scale -> semantics -> coverage validation -> per-class math -> TakeoffResult.

The product concept (plan Global Constraints): Claude decides MEANING — what
each candidate IS, expressed as class ids. THIS module computes every quantity,
in code, from geometry. No token anywhere else asks the model for a number.
"""
from dataclasses import dataclass
from pathlib import Path

from .geometry_regions import regions_from_fills, regions_from_polygonize
from .geometry_runs import runs_from_strokes
from .models import Anchor, CandidateRegion, CandidateRun, ClassSpec, Measurement, TakeoffResult
from .pdf_extract import extract_sheet, page_text_upper
from .scale import apply_override, parse_scale
from .semantics import ClaudeSemanticsClient, SemanticsClient, anchor_candidates

MAX_CANDIDATES = 400      # mirrors semantics.MAX_CANDIDATES: truncate BEFORE the semantics call
CONTAINMENT_FRAC = 0.95   # containment-merge guard (double-count guard)
QA_LIST_LIMIT = 20        # ids enumerated in QA lines: cap for readability


@dataclass
class MeasureOutcome:
    result: TakeoffResult
    regions: list[CandidateRegion]     # as consumed (truncated when overflowed)
    runs: list[CandidateRun]
    anchors: list[Anchor]


def _dedupe_regions(regions: list[CandidateRegion]) -> list[CandidateRegion]:
    """Drop regions >=95% contained in an earlier region (double-count guard).

    Fills come first in the merged list, so a polygonize re-find of a filled
    pad (identical rect) is dropped — never the pad itself.
    """
    kept: list[CandidateRegion] = []
    for c in regions:
        if any(
            r.polygon.intersection(c.polygon).area >= CONTAINMENT_FRAC * c.polygon.area
            for r in kept
        ):
            continue
        kept.append(c)
    return kept


def _ids(cands) -> str:
    """Comma-joined candidate ids for QA lines; cap at QA_LIST_LIMIT."""
    shown = [c.id for c in cands[:QA_LIST_LIMIT]]
    if len(cands) > QA_LIST_LIMIT:
        shown.append(f"... {len(cands) - QA_LIST_LIMIT} more")
    return ", ".join(shown)


def _weight(c) -> float:
    """Quantity contribution of one candidate — the histogram 'volume'."""
    if isinstance(c, CandidateRegion):
        return c.area_pt2
    if isinstance(c, CandidateRun):
        return c.length_pt
    return 1.0


def _key_mixed(counts: dict, weights: dict, total_w: float) -> bool:
    """One key value >=80% of candidate counts while another key holds >=20%
    of the class's total quantity (a typical fill-border relationship)."""
    n = sum(counts.values())
    if n < 3:  # no evidence to claim (<3 candidates)
        return False
    for dominant, share in counts.items():
        if share / n >= 0.8 and any(
            o != dominant and weights[o] / total_w >= 0.2 for o in counts
        ):
            return True
    return False


def _mixed_evidence(cls: ClassSpec, cands: list) -> bool:
    """M5 chain-consistency: is this class's evidence self-consistent?

    Two keyed histograms — source and fill_rgb (None excluded). Skip <3
    candidates: nothing to claim.
    """
    if len(cands) < 3:
        return False
    for key_fn in (
        lambda c: c.source if isinstance(c, CandidateRegion) else None,
        lambda c: c.fill_rgb if isinstance(c, CandidateRegion) else None,
    ):
        counts: dict = {}
        weights: dict = {}
        for c in cands:
            k = key_fn(c)
            if k is None:
                continue
            counts[k] = counts.get(k, 0) + 1
            weights[k] = weights.get(k, 0) + _weight(c)
        if not counts:
            continue
        if _key_mixed(counts, weights, sum(weights.values())):
            return True
    return False


def measure(pdf_path: str, user_prompt: str = "",
            semantics: SemanticsClient | None = None,
            scale_override: int | None = None) -> MeasureOutcome:
    semantics = semantics or ClaudeSemanticsClient()
    sheet = extract_sheet(pdf_path)

    # ponytail: both extraction paths MUST run at their default thresholds —
    # regions_from_polygonize precomputes id_start from regions_from_fills at
    # the fills default (0.5); a non-default fills threshold here would desync
    # polygonize ids. Call with defaults, never override.
    regions = _dedupe_regions(regions_from_fills(sheet) + regions_from_polygonize(sheet))
    runs = runs_from_strokes(sheet)
    anchors = anchor_candidates(sheet)

    # Zero-candidate short-circuit: a blank candidate table still costs a
    # Claude call and may collect hallucinated classes.
    if not (regions or runs or anchors):
        return MeasureOutcome(
            result=TakeoffResult(
                sheet_name=Path(pdf_path).stem, workspace="0 trades x 1 sheet",
                measurements=[], overflowed=False,
                qa=["no candidates found on sheet — human review"],
            ),
            regions=[], runs=[], anchors=[],
        )

    qa: list[str] = []
    text = page_text_upper(sheet.words)
    effective = (apply_override(text, scale_override)
                 if scale_override is not None else parse_scale(text))
    if effective is None:
        qa.append("scale text ambiguous or missing — verify before use")
    m_per_pt = effective.m_per_pt() if effective is not None else None

    candidates = [*regions, *runs, *anchors]  # sorted: regions, runs, anchors
    overflowed = False
    if len(candidates) > MAX_CANDIDATES:
        overflowed = True
        dropped = candidates[MAX_CANDIDATES:]
        candidates = candidates[:MAX_CANDIDATES]
        qa.append(f"sheet overflowed; measured first {MAX_CANDIDATES} candidates; "
                  f"untaken ids: {_ids(dropped)}")
    regions = [c for c in candidates if isinstance(c, CandidateRegion)]
    runs = [c for c in candidates if isinstance(c, CandidateRun)]
    anchors = [c for c in candidates if isinstance(c, Anchor)]

    sem = semantics.sheet_semantics(sheet, regions, runs, anchors)

    # Coverage validation (never silently drop): every candidate id in exactly
    # one of region_class / run_class / anchor_class / ignore_ids.
    known = {c.id for c in candidates}
    claimed = (set(sem.region_class) | set(sem.run_class)
               | set(sem.anchor_class) | set(sem.ignore_ids))
    unknown = sorted(claimed - known)  # hallucinated ids: drop, do not crash
    if unknown:
        qa.append(f"semantics returned unknown ids: {', '.join(unknown)}")
    known_classes = {c.id for c in sem.classes}

    assign: dict[str, str] = {}   # candidate id -> class id
    for c in candidates:
        if c.id in sem.ignore_ids:
            continue  # ignore wins over a contradictory map entry
        cls_id = None
        if c.id in sem.region_class:
            cls_id = sem.region_class[c.id]
        elif c.id in sem.run_class:
            cls_id = sem.run_class[c.id]
        elif c.id in sem.anchor_class:
            cls_id = sem.anchor_class[c.id]
        if cls_id is not None and cls_id in known_classes:
            assign[c.id] = cls_id

    unclassified = [c.id for c in candidates if c.id not in assign]
    if unclassified:
        qa.append(f"not measured: {len(unclassified)} candidates unclassified — human review")
    ignored = [cid for cid in sem.ignore_ids if cid in known]
    if ignored:
        qa.append(f"not measured: {len(ignored)} candidates ignored by semantics — human review")

    if effective is not None and sem.scale_factor != effective.factor:
        qa.append(f"scale ambiguity: text says 1:{effective.factor}, "
                  f"Claude says 1:{sem.scale_factor} — verify")

    if user_prompt.strip():
        target = semantics.prompt_classes(user_prompt, sem.classes)
        if target.not_found:
            qa.append(f"prompt terms not in legend: {', '.join(target.not_found)}")
        target_ids = set(target.target_ids)
    else:
        target_ids = {c.id for c in sem.classes}  # empty prompt -> all classes

    groups: dict[str, list] = {c.id: [] for c in sem.classes}
    for c in candidates:
        cls_id = assign.get(c.id)
        if cls_id not in groups:
            continue
        groups[cls_id].append(c)

    measurements: list[Measurement] = []
    for cls in sem.classes:
        if cls.id not in target_ids:
            continue  # prompt asked for other classes
        cands = groups[cls.id]
        if not cands:
            continue
        # HARD RULE: quantities are computed ONLY here, from geometry, in code.
        # Claude never returns a number; it returns class ids. See plan Global Constraints.
        if cls.measure == "area":
            raw = sum(c.area_pt2 for c in cands if isinstance(c, CandidateRegion))
            quantity = raw * m_per_pt * m_per_pt if m_per_pt is not None else raw
            unit = "m2" if m_per_pt is not None else "pt"
        elif cls.measure == "length":
            raw = sum(c.length_pt for c in cands if isinstance(c, CandidateRun))
            quantity = raw * m_per_pt if m_per_pt is not None else raw
            unit = "m" if m_per_pt is not None else "pt"
        else:  # count
            quantity, unit = float(len(cands)), "pcs"
        if _mixed_evidence(cls, cands):
            confidence = 0.5
            qa.append(f"class {cls.name_en}: mixed evidence — review")
        else:
            confidence = 1.0
        measurements.append(Measurement(
            class_id=cls.id, class_name_en=cls.name_en, measure=cls.measure,
            quantity=quantity, unit=unit,
            source_ids=[c.id for c in cands], confidence=confidence,
        ))

    result = TakeoffResult(
        sheet_name=Path(pdf_path).stem,
        workspace=f"{len(measurements)} trades x 1 sheet",
        measurements=measurements, overflowed=overflowed, qa=qa,
    )
    return MeasureOutcome(result=result, regions=regions, runs=runs, anchors=anchors)
