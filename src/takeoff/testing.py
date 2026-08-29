"""Scripted deterministic SemanticsClient — the ``--mock`` path (no API).

Imports only from this package (takeoff.semantics types), never from tests/,
so it works whether or not tests/ is importable. It maps candidates by
position, not by vision: fills by index (0 -> asphalt, 1 -> planting, rest ->
asphalt, so a 401-grid-fills flood still produces valid output), polygonize
regions -> playlot UNLESS their bbox contains any word text (legend/schedule
boxes are rings TOO — those go to ignore_ids; a bare ring does not), runs by
index (0 -> water pipe, rest -> curve), anchors whose word starts with MH ->
manhole. Anything unmapped -> ignore_ids.

The v2 fixture raises the difficulty: 3 fills (no stroke-only rings, no runs)
+ MH anchors, scale 1:200. The scripted v2 map dispatches on the fills count
(exactly 3 — v1's fixtures carry 2/8/401 fills, so the counts never collide);
it is scale-factor-agnostic by design: the client never receives the sheet
scale, the mapping is by candidate index only, and the 200 exits with the map.
"""
from .models import ClassSpec
from .semantics import PromptTarget, SheetSemantics

def _has_words(words, bbox) -> bool:
    """Any fitz word bbox (x0, y0, x1, y1, ...) intersects the region bbox?

    Controller ruling for the legend-ring discriminator: a legend/schedule box
    contains text, a bare playlot ring does not (fixture-true).
    """
    return any(
        not (w[2] < bbox[0] or w[0] > bbox[2] or w[3] < bbox[1] or w[1] > bbox[3])
        for w in words)


LEGEND_CLASSES = [
    ClassSpec(id="C1", name_en="Asphalt", measure="area"),
    ClassSpec(id="C2", name_en="Planting", measure="area"),
    ClassSpec(id="C3", name_en="Playlot", measure="area"),
    ClassSpec(id="C4", name_en="Water Pipe", measure="length"),
    ClassSpec(id="C5", name_en="Curve", measure="length"),
    ClassSpec(id="C6", name_en="Manhole", measure="count"),
]

V2_CLASSES = [
    ClassSpec(id="C1", name_en="Asphalt", measure="area"),
    ClassSpec(id="C2", name_en="Planting", measure="area"),
    ClassSpec(id="C3", name_en="Paving", measure="area"),
    ClassSpec(id="C4", name_en="Manhole", measure="count"),
]


class FakeSemantics:
    """Deterministic stand-in for ClaudeSemanticsClient.

    sheet_semantics: scripted mapping (see module docstring); scale_factor is
    100 for v1's fixtures, 200 for the v2 fixture (dispatched on the fills
    count). prompt_classes: empty prompt -> all class ids; non-empty prompt ->
    all ids when every word matches a class (name_en/name_ms, substring
    match), else the ids of the classes hit by the matched words, with
    unmatched words in not_found.
    """

    def sheet_semantics(self, sheet, regions: list, runs: list,
                        anchors: list) -> SheetSemantics:
        fills = [c for c in regions if c.source == "fill"]
        if len(fills) == 3:
            # v2 fixture (task 13): 3 fills -> v2 classes in fixture order,
            # anchors (MH-12/MH-34) -> the anchor class. No rings, no runs.
            region_class = {c.id: ("C1", "C2", "C3")[i]
                            for i, c in enumerate(fills)}
            return SheetSemantics(
                scale_factor=200,
                classes=[ClassSpec(id=c.id, name_en=c.name_en, measure=c.measure,
                                   name_ms=c.name_ms) for c in V2_CLASSES],
                region_class=region_class, run_class={},
                anchor_class={a.id: "C4" for a in anchors}, ignore_ids=[],
            )
        region_class, run_class, anchor_class = {}, {}, {}
        fill_idx = 0
        ignored = []
        for c in regions:
            if c.source == "fill":
                region_class[c.id] = "C2" if fill_idx == 1 else "C1"
                fill_idx += 1
            elif _has_words(sheet.words, c.bbox):
                ignored.append(c.id)  # text-carrying ring: legend/schedule box
            else:
                region_class[c.id] = "C3"  # textless ring -> playlot
        for i, c in enumerate(runs):
            run_class[c.id] = "C4" if i == 0 else "C5"
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
