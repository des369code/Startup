"""Scripted deterministic SemanticsClient — the ``--mock`` path (no API).

Imports only from this package (takeoff.semantics types), never from tests/,
so it works whether or not tests/ is importable. It maps candidates by
position, not by vision: fills by index (0 -> asphalt, 1 -> planting, rest ->
asphalt, so a 401-grid-fills flood still produces valid output), polygonize
regions -> playlot, runs by index (0 -> water pipe, rest -> curve), anchors
whose word starts with MH -> manhole. Anything unmapped -> ignore_ids.
"""
from .models import ClassSpec
from .semantics import PromptTarget, SheetSemantics

LEGEND_CLASSES = [
    ClassSpec(id="C1", name_en="Asphalt", measure="area"),
    ClassSpec(id="C2", name_en="Planting", measure="area"),
    ClassSpec(id="C3", name_en="Playlot", measure="area"),
    ClassSpec(id="C4", name_en="Water Pipe", measure="length"),
    ClassSpec(id="C5", name_en="Curve", measure="length"),
    ClassSpec(id="C6", name_en="Manhole", measure="count"),
]


class FakeSemantics:
    """Deterministic stand-in for ClaudeSemanticsClient.

    sheet_semantics: scripted mapping (see module docstring); scale_factor is
    always 100 (the fixtures' sheet scale). prompt_classes: empty prompt ->
    all class ids; non-empty prompt -> all ids when every word matches a class
    (name_en/name_ms, substring match), else the ids of the classes hit by the
    matched words, with unmatched words in not_found.
    """

    def sheet_semantics(self, sheet, regions: list, runs: list,
                        anchors: list) -> SheetSemantics:
        region_class, run_class, anchor_class = {}, {}, {}
        fill_idx = 0
        for c in regions:
            if c.source == "fill":
                region_class[c.id] = "C2" if fill_idx == 1 else "C1"
                fill_idx += 1
            else:
                region_class[c.id] = "C3"  # polygonize -> playlot
        for i, c in enumerate(runs):
            run_class[c.id] = "C4" if i == 0 else "C5"
        ignored = []
        for a in anchors:
            if a.word.upper().startswith("MH"):
                anchor_class[a.id] = "C6"
            else:
                ignored.append(a.id)
        return SheetSemantics(
            scale_factor=100,
            classes=[ClassSpec(id=c.id, name_en=c.name_en, measure=c.measure,
                               name_ms=c.name_ms) for c in LEGEND_CLASSES],
            region_class=region_class, run_class=run_class,
            anchor_class=anchor_class, ignore_ids=ignored,
        )

    def prompt_classes(self, user_prompt: str,
                       classes: list[ClassSpec]) -> PromptTarget:
        if not user_prompt.strip():
            return PromptTarget(target_ids=[c.id for c in classes], not_found=[])
        words = {w.strip(" .,;:()[]'\"`").lower()
                 for w in user_prompt.split() if w.strip()}
        target_ids, matched_words = [], set()
        for c in classes:
            names = {c.name_en.lower()}
            if c.name_ms:
                names.add(c.name_ms.lower())
            if any(w in n for w in words for n in names):
                target_ids.append(c.id)
                matched_words.update(w for w in words
                                     if any(w in n for n in names))
        not_found = sorted(words - matched_words)
        if not not_found:
            target_ids = [c.id for c in classes]  # fully matched -> all ids
        return PromptTarget(target_ids=target_ids, not_found=not_found)
