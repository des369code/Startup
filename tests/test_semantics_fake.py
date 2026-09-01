"""Semantics-layer tests: schema round-trip, scripted fake client, tile-merge
unification, anchor extraction, renderer, overflow guard, system-prompt pin.

No live API calls here — the live path is ``@pytest.mark.live`` and is skipped
by default (``pytest -m "not live"``, requires ANTHROPIC_API_KEY).
"""
import hashlib
import io

import pytest
from PIL import Image
from shapely.geometry import box

from takeoff.geometry_regions import regions_from_fills, regions_from_polygonize
from takeoff.geometry_runs import runs_from_strokes
from takeoff.models import CandidateRegion, ClassSpec, SheetData
from takeoff.pdf_extract import extract_sheet
from takeoff.semantics import (
    SYSTEM_PROMPT,
    CandidateOverflow,
    ClaudeSemanticsClient,
    PromptTarget,
    SheetSemantics,
    _merge_tile_results,
    anchor_candidates,
    rendered_with_ids,
)
from takeoff.testing import FakeSemantics
from tests.fixtures import make_synthetic_drawing


# ---------------------------------------------------------------- fixtures

def _png_bytes(size=(16, 16), color="white"):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


def _sheet(words=(), pages=(400.0, 400.0)):
    """Synthetic SheetData: any PNG will do — semantics renderers only need
    page dimensions and pixels."""
    return SheetData(page_w=pages[0], page_h=pages[1], paths=[], words=list(words),
                     png_bytes=_png_bytes())


def _grid_regions(n, w=400.0, h=400.0, size=5.0):
    """n CandidateRegions spread over the page (fills, source='fill') so the
    candidate flood lands in all four quadrants."""
    nrows = (n + 19) // 20
    out = []
    for i in range(n):
        cx = (i % 20 + 0.5) * w / 20
        cy = (i // 20 + 0.5) * h / nrows
        out.append(CandidateRegion(
            id=f"R{i}", polygon=box(cx - size, cy - size, cx + size, cy + size),
            bbox=(cx - size, cy - size, cx + size, cy + size),
            area_pt2=(2 * size) ** 2, fill_rgb=(0, 0, 0), source="fill",
        ))
    return out


def _word(x, text):
    return (x, 0.0, x + 20.0, 10.0, text, 0, 0, 0)


# ------------------------------------------------------------ schema tests

def test_brief_schema_roundtrip_accepts_known_classes():
    fake = FakeSemantics()
    result = fake.sheet_semantics(sheet=None, regions=[], runs=[], anchors=[])  # noqa
    assert isinstance(result, SheetSemantics)


def test_model_validate_coerces_class_dicts_to_classspec():
    # The API returns JSON; pydantic must coerce nested class dicts into
    # ClassSpec dataclass instances (SheetSemantics declares list[ClassSpec]).
    parsed = SheetSemantics.model_validate({
        "scale_factor": 100,
        "classes": [{"id": "C1", "name_en": "Asphalt", "measure": "area"}],
        "region_class": {"R0": "C1"},
        "run_class": {}, "anchor_class": {},
        "ignore_ids": ["R99"],
    })
    assert isinstance(parsed, SheetSemantics)
    assert isinstance(parsed.classes[0], ClassSpec)
    assert parsed.classes[0].name_en == "Asphalt"
    assert parsed.region_class == {"R0": "C1"}
    assert parsed.ignore_ids == ["R99"]


def test_prompt_target_shape():
    t = PromptTarget.model_validate({"target_ids": ["C1"], "not_found": ["kerb"]})
    assert t.target_ids == ["C1"] and t.not_found == ["kerb"]


# ---------------------------------------------------------- tiling / merge

def test_tile_merge_unifies_conflicting_registries():
    # Two tile results assign C1/C2/C3 independently; merge must key on
    # (name_en.lower(), measure), renumber, and rebuild every mapping dict.
    tile_a = SheetSemantics(
        scale_factor=100,
        classes=[
            ClassSpec(id="C1", name_en="Asphalt", measure="area"),
            ClassSpec(id="C2", name_en="Water Pipe", measure="length"),
            ClassSpec(id="C3", name_en="Manhole", measure="count"),
        ],
        region_class={"R0": "C1"},
        run_class={"RUN0": "C2"},
        anchor_class={"A0": "C3"},
        ignore_ids=["R9"],
    )
    tile_b = SheetSemantics(
        scale_factor=100,
        classes=[
            ClassSpec(id="C1", name_en="Planting", measure="area"),
            ClassSpec(id="C2", name_en="Curve", measure="length"),
            ClassSpec(id="C3", name_en="Manhole", measure="count"),  # same key as A
        ],
        region_class={"R1": "C1"},
        run_class={"RUN1": "C2"},
        anchor_class={"A1": "C3"},
        ignore_ids=["R8"],
    )
    merged = _merge_tile_results([tile_a, tile_b])
    assert [(c.id, c.name_en, c.measure) for c in merged.classes] == [
        ("C1", "Asphalt", "area"),
        ("C2", "Water Pipe", "length"),
        ("C3", "Manhole", "count"),
        ("C4", "Planting", "area"),     # tile B's C1 renumbered
        ("C5", "Curve", "length"),      # tile B's C2 renumbered
    ]
    assert merged.region_class == {"R0": "C1", "R1": "C4"}
    assert merged.run_class == {"RUN0": "C2", "RUN1": "C5"}
    assert merged.anchor_class == {"A0": "C3", "A1": "C3"}   # Manhole deduped
    assert set(merged.ignore_ids) == {"R9", "R8"}
    assert merged.scale_factor == 100


class _StubClient(ClaudeSemanticsClient):
    """Counts LLM calls; returns one fixed class per call (never hits the API)."""
    def __init__(self):
        super().__init__(client=object())
        self.calls = 0
        self.tables = []

    def _classify(self, image_bytes: bytes, table_text: str) -> SheetSemantics:
        self.calls += 1
        self.tables.append((len(image_bytes), table_text))
        return SheetSemantics(
            classes=[ClassSpec(id="C1", name_en="Asphalt", measure="area")],
            region_class={}, run_class={}, anchor_class={}, ignore_ids=[],
        )


def test_tile_pipeline_splits_over_100_into_four_calls():
    stub = _StubClient()
    out = stub.sheet_semantics(_sheet(), _grid_regions(120), [], [])
    assert stub.calls == 4                       # 2x2 grid, one call per pushed tile
    assert [c.name_en for c in out.classes] == ["Asphalt"]  # deduped across tiles


def test_tile_pipeline_one_call_until_threshold():
    stub = _StubClient()
    stub.sheet_semantics(_sheet(), _grid_regions(100), [], [])
    assert stub.calls == 1                       # == 100 is not > 100 -> no tiling
    assert stub.tables[0][1]  # table text non-empty


def test_tile_pipeline_maps_all_candidates_at_400():
    # boundary: 400 (== cap) tiles; 401 must overflow instead (next test)
    stub = _StubClient()
    out = stub.sheet_semantics(_sheet(), _grid_regions(400), [], [])
    assert stub.calls == 4
    assert len(out.classes) == 1


def test_sheet_semantics_overflow_raises():
    with pytest.raises(CandidateOverflow):
        _StubClient().sheet_semantics(_sheet(), _grid_regions(401), [], [])


# ---------------------------------------------------------------- anchors

def test_anchor_candidates_extracts_symbols_and_excludes_pure_numbers():
    sheet = _sheet([
        _word(0, "MH-01"), _word(30, "MH-02"), _word(60, "1500"), _word(90, "2500"),
        _word(120, "100CD"), _word(150, "PLAN"), _word(180, "CH_5"), _word(210, "24.0"),
    ])
    anchors = anchor_candidates(sheet)
    assert [a.word for a in anchors] == ["MH-01", "MH-02", "100CD", "CH_5"]
    assert [a.id for a in anchors] == ["A0", "A1", "A2", "A3"]


def test_anchor_candidates_caps_at_100():
    sheet = _sheet([_word(i * 2.0, f"MH-{i:03d}") for i in range(150)])
    anchors = anchor_candidates(sheet)
    assert len(anchors) == 100
    assert anchors[-1].word == "MH-099"


def test_anchor_candidate_geometry():
    sheet = _sheet([_word(10, "MH-01")])
    anchors = anchor_candidates(sheet)
    a = anchors[0]
    assert a.bbox == (10.0, 0.0, 30.0, 10.0)
    assert a.centroid == (20.0, 5.0)


# -------------------------------------------------------------- renderer

def test_rendered_with_ids_returns_png(tmp_path):
    pdf, _ = make_synthetic_drawing(tmp_path)
    sheet = extract_sheet(pdf)
    regions = regions_from_fills(sheet)
    assert len(regions) == 2
    png = rendered_with_ids(sheet, regions)
    assert png.startswith(b"\x89PNG")
    assert png != sheet.png_bytes              # labels actually changed pixels


# ------------------------------------------------------------ system prompt

def test_system_prompt_sha256_pinned():
    # CEO review: the cached system prompt is the sheet_semantics identity;
    # any edit must fail this test (plan: stable cached prefix).
    assert hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest() == (
        "faf7814ee6675426eacefc5bc177506130062e23fd8bcd0d5621731a3d42056d"
    )


def test_system_prompt_contains_hard_rule_wording():
    assert "never compute quantities" in SYSTEM_PROMPT
    assert "never estimate areas" in SYSTEM_PROMPT
    assert "never measure" in SYSTEM_PROMPT
    assert "ignore_ids" in SYSTEM_PROMPT


# ----------------------------------------------------------- fake client

def test_fake_semantics_maps_synthetic_sheet(tmp_path):
    pdf, _ = make_synthetic_drawing(tmp_path)
    sheet = extract_sheet(pdf)
    regions = regions_from_fills(sheet) + regions_from_polygonize(sheet)
    runs = runs_from_strokes(sheet)
    anchors = anchor_candidates(sheet)
    out = FakeSemantics().sheet_semantics(sheet, regions, runs, anchors)

    assert out.scale_factor == 100
    name = {c.id: c.name_en for c in out.classes}
    # fills by index: R0 asphalt, R1 planting; polygonize -> playlot
    fills = [c for c in regions if c.source == "fill"]
    assert name[out.region_class[fills[0].id]] == "Asphalt"
    assert name[out.region_class[fills[1].id]] == "Planting"
    poly = [c for c in regions if c.source == "polygonize"]
    assert name[out.region_class[poly[0].id]] == "Playlot"
    # runs by index: RUN0 water pipe, rest curve
    assert name[out.run_class[runs[0].id]] == "Water Pipe"
    assert name[out.run_class[runs[1].id]] == "Curve"
    # anchors whose word starts with MH -> manhole (count)
    mh = [a for a in anchors if a.word.startswith("MH")]
    assert mh and name[out.anchor_class[mh[0].id]] == "Manhole"
    assert isinstance(out.anchor_class[mh[0].id], str)

    # coverage: every candidate id sits in exactly one of the maps or ignore
    region_ids = {c.id for c in regions}
    run_ids = {c.id for c in runs}
    anchor_ids = {a.id for a in anchors}
    assert region_ids & run_ids == set() and run_ids & anchor_ids == set()
    mapped = (set(out.region_class) | set(out.run_class) | set(out.anchor_class))
    for cid in region_ids | run_ids | anchor_ids:
        assert cid not in mapped or cid not in out.ignore_ids
        assert cid in mapped or cid in out.ignore_ids


def test_fake_semantics_busy_grid_fills_map_to_asphalt():
    # 401 grid fills (make_busy_drawing's case at semantics level): maps
    # remain valid — remaining fills fall to asphalt, nothing crashes.
    fake = FakeSemantics()
    regions = _grid_regions(401)
    out = fake.sheet_semantics(_sheet(), regions, [], [])
    assert len(out.region_class) == len(regions)
    name = {c.id: c.name_en for c in out.classes}
    assert name[out.region_class["R0"]] == "Asphalt"
    assert name[out.region_class["R1"]] == "Planting"
    assert name[out.region_class["R399"]] == "Asphalt"
    assert out.scale_factor == 100


def test_fake_prompt_classes_scripted():
    fake = FakeSemantics()
    classes = [
        ClassSpec(id="C1", name_en="Asphalt", measure="area"),
        ClassSpec(id="C2", name_en="Water Pipe", measure="length"),
    ]
    # empty prompt -> every class id
    t = fake.prompt_classes("", classes)
    assert isinstance(t, PromptTarget)
    assert t.target_ids == ["C1", "C2"] and t.not_found == []
    # fully-matched prompt -> all ids too
    t2 = fake.prompt_classes("asphalt pipe", classes)
    assert t2.target_ids == ["C1", "C2"] and t2.not_found == []
    # unmatched words -> not_found; target ids = matched classes
    t3 = fake.prompt_classes("asphalt wibble", classes)
    assert t3.target_ids == ["C1"] and t3.not_found == ["wibble"]


# ------------------------------------------------------------------ live

@pytest.mark.live
def test_live_sheet_semantics_on_fixture(tmp_path):
    # requires LIVE=1 + ANTHROPIC_API_KEY or `ant auth login`
    pdf, _ = make_synthetic_drawing(tmp_path)
    sheet = extract_sheet(pdf)
    regions = regions_from_fills(sheet) + regions_from_polygonize(sheet)
    runs = runs_from_strokes(sheet)
    anchors = anchor_candidates(sheet)
    out = ClaudeSemanticsClient().sheet_semantics(sheet, regions, runs, anchors)
    assert isinstance(out, SheetSemantics)
    assert out.classes  # legend was readable


# ------------------------------------------------------------------ fallback parse

def test_extract_json_recovers_markdown_wrapped_object():
    from takeoff.semantics import SemanticsError, _extract_json

    wrapped = "**Registry**\n\n```json\n{\"classes\": []}\n```\nnotes here"
    assert _extract_json(wrapped) == '{"classes": []}'
    with pytest.raises(SemanticsError):
        _extract_json("no json object, only a markdown table | a | b |")
