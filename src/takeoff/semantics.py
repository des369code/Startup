"""Semantics layer: Claude assigns MEANING; the engine computes all MATH.

``sheet_semantics`` and ``prompt_classes`` are the ONLY two LLM calls in the
product. HARD RULE (non-negotiable): no token in here asks the model for a
quantity — no prompt asks for an area, a length, or a sum. The model returns
class ids, a legend registry, and ignore_ids only; every number on the sheet
is measured later by the engine's own code (see measure.py).
"""
import base64
import io
import json
import re
from typing import Protocol

import anthropic
from PIL import Image, ImageDraw, ImageFont
from pydantic import BaseModel

from .models import Anchor, CandidateRegion, CandidateRun, ClassSpec, SheetData

DPI = 200                 # every render in this module and the pipeline (M3)
MAX_CANDIDATES = 400      # > this: raise CandidateOverflow; measure() truncates first
TILE_THRESHOLD = 100      # > this: 2x2 grid render, one semantic call per tile
ANCHOR_CAP = 100          # mirrors the candidate cap: dimension floods must not
                          # starve count measures

# --------------------------------------------------------------------------
# System prompt — STABLE. It is the first-and-only cached system block
# (cache_control ephemeral) and never varies between calls, so its SHA-256 is
# pinned by tests/test_semantics_fake.py::test_system_prompt_sha256_pinned.
# Any edit to the wording below MUST update the pin.
# --------------------------------------------------------------------------
SYSTEM_PROMPT = (
    "You are a quantity-takeoff semantics engine for Malaysian construction "
    "drawings (JKR/MDB style). You decide MEANING, and only meaning: what each "
    "candidate region, run, or text symbol IS, and which legend entry it belongs "
    "to. The engine computes every quantity in code afterwards; you never touch "
    "arithmetic.\n\n"
    "You return CLASS IDs and REGISTRY entries only. You never compute "
    "quantities, never estimate areas, never measure. The candidate table "
    "carries descriptive numbers (area_pt2, length_pt, bbox) so you can tell a "
    "filled pad from a thin run from a small symbol; those numbers are context "
    "for identification only — never echo, derive, sum, average or restate any "
    "of them in your output.\n\n"
    "Output rules:\n"
    "- Registry: every class you declare gets one entry: id (\"C1\", \"C2\", ... "
    "— arbitrary short labels), name_en (plain English), measure (\"area\" for "
    "surfaces, \"length\" for runs, \"count\" for discrete symbols), name_ms "
    "(Malay term if known, optional).\n"
    "- Every candidate id must be mapped to exactly one class id, or listed in "
    "ignore_ids. Legend swatches, title-block art, note frames, borders, "
    "dimension callouts, and anything that is not a takeoff item go to "
    "ignore_ids.\n"
    "- Anchor ids (A0...) are text symbols (for example MH-01); map them to "
    "\"count\" classes only.\n"
    "- scale_factor: the drawing scale you read from the sheet, e.g. 100 for "
    "1:100. Leave it at 1 when the sheet does not say — code cross-checks this "
    "against the title-block regex parse anyway.\n\n"
    "If unsure, you omit the id (put in ignore_ids) rather than guess."
)

_SHEET_TASK = (
    "The image is a rendered page (or a 2x2 tile of one) of a Malaysian "
    "construction drawing; red labels mark every candidate with its id.\n"
    "The candidate table lists id, kind (area / length / count), bbox in page "
    "points, and descriptive geometry (area_pt2 / length_pt) recorded in paper "
    "point units so you can recognise what each shape is. Those numbers are "
    "context for identification only: never compute, sum, convert, or repeat "
    "any of them. Your reply is the registry plus id->class mappings — see the "
    "system instructions.\n\nCandidates:\n"
)

_PROMPT_TASK = (
    "Map the words of a user's prompt onto the legend classes. Reply with class "
    "ids only: target_ids = classes the prompt asks for; not_found = prompt "
    "words that match no class. Never return quantities.\n\n"
)


class SheetSemantics(BaseModel):
    scale_factor: int = 1            # CROSS-CHECK ONLY. Regex parse in scale.py is
                                     # primary; if Claude's factor differs, measure()
                                     # adds a QA flag and keeps the regex value.
    classes: list[ClassSpec]         # legend -> registry
    region_class: dict[str, str]     # candidate id -> class id
    run_class: dict[str, str]
    anchor_class: dict[str, str]     # anchor id -> class id ("count" measures)
    ignore_ids: list[str]            # candidates Claude says are legend swatches/frame/etc.


class PromptTarget(BaseModel):
    target_ids: list[str]            # class ids the user's prompt asks for
    not_found: list[str]             # prompt words with no class match — measure() must QA-flag these


class CandidateOverflow(Exception):
    """More candidates than MAX_CANDIDATES — the caller truncates + sets
    overflowed (see measure.py)."""


class SemanticsError(Exception):
    """The model call did not return a parsed output (refusal / stop)."""


class SemanticsClient(Protocol):
    def sheet_semantics(self, sheet: SheetData, regions: list, runs: list,
                        anchors: list) -> SheetSemantics: ...

    def prompt_classes(self, user_prompt: str, classes: list[ClassSpec]) -> PromptTarget: ...


class ClaudeSemanticsClient:
    """The two LLM calls. Everything else (rendering, tiling, merge, tables)
    is pure code that the tests exercise without an API key."""

    def __init__(self, client: anthropic.Anthropic | None = None):
        self._client = client or anthropic.Anthropic()

    def sheet_semantics(self, sheet: SheetData, regions: list, runs: list,
                        anchors: list) -> SheetSemantics:
        """One call from the caller's side; tiling (2x2, one call per tile)
        is internal, and per-tile results merge into one registry."""
        candidates = [*regions, *runs, *anchors]
        if len(candidates) > MAX_CANDIDATES:
            raise CandidateOverflow(
                f"{len(candidates)} candidates exceed the {MAX_CANDIDATES} cap"
            )
        if not candidates:
            # A blank candidate table still costs a Claude call and may
            # collect hallucinated classes — same rule as measure()'s
            # zero-candidate short circuit.
            return SheetSemantics()
        if len(candidates) > TILE_THRESHOLD:
            results = []
            for rect, group in _tile_groups(candidates, sheet.page_w, sheet.page_h):
                if not group:
                    continue  # empty quadrant: no call, no table
                results.append(self._classify(*_tile_render(sheet, rect, group)))
            return _merge_tile_results(results)
        return self._classify(*_page_render(sheet, candidates))

    def prompt_classes(self, user_prompt: str, classes: list[ClassSpec]) -> PromptTarget:
        registry = [
            {"id": c.id, "name_en": c.name_en, "name_ms": c.name_ms,
             "measure": c.measure}
            for c in classes
        ]
        task = _PROMPT_TASK + f"User prompt: {user_prompt!r}\n\nRegistry:\n" + json.dumps(registry, indent=1)
        return self._classify_text(task)

    # -- the only places that touch the API ---------------------------------
    def _classify(self, image_bytes: bytes, table_text: str) -> SheetSemantics:
        b64 = base64.standard_b64encode(image_bytes).decode("ascii")
        response = self._client.beta.messages.parse(
            model="claude-opus-5",
            max_tokens=16000,
            system=[{"type": "text", "text": SYSTEM_PROMPT,
                     "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": [
                {"type": "image",
                 "source": {"type": "base64", "media_type": "image/png", "data": b64}},
                {"type": "text", "text": table_text},
            ]}],
            thinking={"type": "adaptive"},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_format=SheetSemantics,
        )
        out = response.parsed_output
        if out is None:
            raise SemanticsError(f"sheet_semantics stopped: {response.stop_reason}")
        return out

    def _classify_text(self, task: str) -> PromptTarget:
        response = self._client.beta.messages.parse(
            model="claude-opus-5",
            max_tokens=16000,
            system=[{"type": "text", "text": SYSTEM_PROMPT,
                     "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": task}],
            thinking={"type": "adaptive"},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_format=PromptTarget,
        )
        out = response.parsed_output
        if out is None:
            raise SemanticsError(f"prompt_classes stopped: {response.stop_reason}")
        return out


# --------------------------------------------------------------------------
# anchors
# --------------------------------------------------------------------------
_SYMBOL_RE = re.compile(r"^([A-Z]{2,6})[- _]?(\d+)$")
_KNOWN_PREFIXES = frozenset({"MH", "CH", "WC", "MP", "CP", "GR", "NH"})


def anchor_candidates(sheet: SheetData, cap: int = ANCHOR_CAP) -> list[Anchor]:
    r"""Text words that look like element symbols -> Anchors, A0.. in sheet order.

    Pass 1: stripped word starts with a known symbol prefix
    (``^([A-Z]{2,6})[- _]?(\d+)$``, prefix in MH/CH/WC/MP/CP/GR/NH).
    Pass 2 (generic): any word containing letters AND digits (e.g. ``100CD``).
    Bare pure-number words (``1500``, ``24.0``) are dimension callouts and are
    EXCLUDED — reconcile.py owns them. ``cap`` (100) mirrors the candidate cap:
    a dimension flood must not starve count measures. Code extracts; Claude
    decides which are measure-worthy.
    """
    out: list[Anchor] = []
    for w in sheet.words:
        if len(out) >= cap:
            break
        text = str(w[4]).strip().upper()
        if not text:
            continue
        m = _SYMBOL_RE.match(text)
        if m is None or m.group(1) not in _KNOWN_PREFIXES:
            if not (any(ch.isalpha() for ch in text)
                    and any(ch.isdigit() for ch in text)):
                continue
        out.append(Anchor(
            id=f"A{len(out)}", word=text, bbox=(w[0], w[1], w[2], w[3]),
            centroid=((w[0] + w[2]) / 2, (w[1] + w[3]) / 2),
        ))
    return out[:cap]


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------
_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",   # linux
    "/System/Library/Fonts/Supplemental/Arial.ttf",      # macOS
    "/Library/Fonts/Arial.ttf",
    "C:/Windows/Fonts/arial.ttf",                        # windows
)
_FONT_CACHE: dict[int, ImageFont.FreeTypeFont | ImageFont.ImageFont] = {}


def _load_font(size: int):
    """ttf font resolver with default-bitmap fallback (paths differ per machine)."""
    font = _FONT_CACHE.get(size)
    if font is not None:
        return font
    for path in _FONT_CANDIDATES:
        try:
            font = ImageFont.truetype(path, size)
            break
        except (OSError, PermissionError):
            continue
    else:
        font = ImageFont.load_default()
    _FONT_CACHE[size] = font
    return font


def _centroid(c) -> tuple[float, float]:
    if isinstance(c, CandidateRegion):
        return (c.polygon.centroid.x, c.polygon.centroid.y)
    x0, y0, x1, y1 = c.bbox
    return ((x0 + x1) / 2, (y0 + y1) / 2)


def _draw_id_labels(img, candidates, origin, kx, ky) -> None:
    """Draw each candidate id at its centroid; font scales with render width
    (labels stay legible at the API's downscale)."""
    d = ImageDraw.Draw(img)
    font = _load_font(max(10, img.width // 200))
    ox, oy = origin
    for c in candidates:
        cx, cy = _centroid(c)
        d.text(((cx - ox) * kx, (cy - oy) * ky), c.id, fill=(255, 0, 0), font=font)


def _draw_and_export(img, candidates, origin, kx, ky) -> tuple[bytes, str]:
    _draw_id_labels(img, candidates, origin, kx, ky)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue(), _candidate_table(candidates, origin)


def _page_render(sheet: SheetData, candidates: list) -> tuple[bytes, str]:
    """Full-page render: px = pt * (img.size / page size), i.e. 200/72 at DPI."""
    img = Image.open(io.BytesIO(sheet.png_bytes)).convert("RGB")
    return _draw_and_export(img, candidates, (0.0, 0.0),
                            img.width / sheet.page_w, img.height / sheet.page_h)


def _tile_render(sheet: SheetData, rect, candidates: list) -> tuple[bytes, str]:
    """One 2x2-quadrant render, cropped from the same 200 DPI page PNG."""
    img = Image.open(io.BytesIO(sheet.png_bytes)).convert("RGB")
    kx, ky = img.width / sheet.page_w, img.height / sheet.page_h
    crop = (int(round(rect[0] * kx)), int(round(rect[1] * ky)),
            int(round(rect[2] * kx)), int(round(rect[3] * ky)))
    tile = img.crop(crop)
    tkx, tky = tile.width / (rect[2] - rect[0]), tile.height / (rect[3] - rect[1])
    return _draw_and_export(tile, candidates, (rect[0], rect[1]), tkx, tky)


def rendered_with_ids(sheet: SheetData, candidates: list) -> bytes:
    """sheet PNG + candidate id labels -> PNG bytes. For annotate/mock QA."""
    img = Image.open(io.BytesIO(sheet.png_bytes)).convert("RGB")
    _draw_id_labels(img, candidates, (0.0, 0.0),
                    img.width / sheet.page_w, img.height / sheet.page_h)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _candidate_table(candidates: list, origin=(0.0, 0.0)) -> str:
    ox, oy = origin
    rows = []
    for c in candidates:
        x0, y0, x1, y1 = c.bbox
        if isinstance(c, CandidateRegion):
            entry = {"id": c.id, "kind": "area", "bbox": [round(x0 - ox, 1), round(y0 - oy, 1),
                                                          round(x1 - ox, 1), round(y1 - oy, 1)],
                     "area_pt2": round(c.area_pt2, 1)}
        elif isinstance(c, CandidateRun):
            entry = {"id": c.id, "kind": "length", "bbox": [round(x0 - ox, 1), round(y0 - oy, 1),
                                                            round(x1 - ox, 1), round(y1 - oy, 1)],
                     "length_pt": round(c.length_pt, 1)}
        else:
            entry = {"id": c.id, "kind": "count", "bbox": [round(x0 - ox, 1), round(y0 - oy, 1),
                                                           round(x1 - ox, 1), round(y1 - oy, 1)],
                     "word": c.word}
        rows.append(entry)
    return _SHEET_TASK + json.dumps(rows, indent=1)


# --------------------------------------------------------------------------
# tiling: 2x2 grid split + per-tile merge back into one registry
# --------------------------------------------------------------------------
def _tile_rects(page_w: float, page_h: float) -> list[tuple]:
    """Quadrant rects in page points, row-major: TL, TR, BL, BR."""
    hw, hh = page_w / 2, page_h / 2
    return [(0.0, 0.0, hw, hh), (hw, 0.0, page_w, hh),
            (0.0, hh, hw, page_h), (hw, hh, page_w, page_h)]


def _tile_groups(candidates: list, page_w: float, page_h: float) -> list[tuple[tuple, list]]:
    """(rect, candidates-in-quadrant) per quadrant; a candidate belongs to the
    quadrant containing its centroid."""
    rects = _tile_rects(page_w, page_h)
    groups = [[] for _ in rects]
    for c in candidates:
        cx, cy = _centroid(c)
        col, row = int(cx >= page_w / 2), int(cy >= page_h / 2)
        groups[row * 2 + col].append(c)
    return list(zip(rects, groups))


def _merge_tile_results(tile_results: list[SheetSemantics]) -> SheetSemantics:
    """Merge per-tile results into one global registry.

    Tile calls assign class ids independently (tile A: C1=Asphalt; tile B:
    C1=Planting), so classes are keyed by (name_en.lower(), measure),
    deduplicated, and renumbered C1..Cn in first-seen order; the mapping dicts
    are rebuilt against the merged registry. ponytail: scale_factor of the
    first tile wins (cross-check only — the regex parse is primary); map
    entries referencing class ids the model invented pass through unchanged,
    and measure()'s validation drops those ids as hallucinations.
    """
    global_classes: list[ClassSpec] = []
    key_to_gid: dict[tuple, str] = {}
    tables: list[dict[str, str]] = []
    for tr in tile_results:
        table = {}
        for cls in tr.classes:
            key = (cls.name_en.lower(), cls.measure)
            gid = key_to_gid.get(key)
            if gid is None:
                gid = f"C{len(global_classes) + 1}"
                key_to_gid[key] = gid
                global_classes.append(ClassSpec(
                    id=gid, name_en=cls.name_en, measure=cls.measure,
                    name_ms=cls.name_ms,
                ))
            table[cls.id] = gid
        tables.append(table)

    merged = SheetSemantics(
        scale_factor=tile_results[0].scale_factor if tile_results else 1,
        classes=global_classes,
        region_class={}, run_class={}, anchor_class={}, ignore_ids=[],
    )
    for tr, table in zip(tile_results, tables):
        for cid, old in tr.region_class.items():
            merged.region_class[cid] = table.get(old, old)
        for cid, old in tr.run_class.items():
            merged.run_class[cid] = table.get(old, old)
        for cid, old in tr.anchor_class.items():
            merged.anchor_class[cid] = table.get(old, old)
        merged.ignore_ids.extend(tr.ignore_ids)
    return merged
