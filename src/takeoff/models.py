"""Shared dataclass vocabulary for the takeoff engine.

All coordinates are in PDF points (float). All quantities are world units.
"""
from dataclasses import dataclass, field
from typing import Any


@dataclass
class CandidateRegion:
    id: str                # "R1"...
    polygon: Any           # shapely Polygon (paper units, points²)
    bbox: tuple            # (x0, y0, x1, y1)
    area_pt2: float        # polygon.area
    fill_rgb: tuple | None
    source: str            # "fill" | "polygonize" — which extraction path produced it


@dataclass
class CandidateRun:
    id: str                # "RUN3"...
    points: list[tuple]    # polyline vertices, paper units (points)
    length_pt: float       # sum of segment lengths
    bbox: tuple


@dataclass
class Anchor:
    id: str                # "A2"...
    word: str              # e.g. "MH-01", "100CD"
    bbox: tuple            # (x0, y0, x1, y1)
    centroid: tuple


@dataclass
class ClassSpec:
    id: str                # code-assigned: "C1"...
    name_en: str
    measure: str           # "area" | "length" | "count"
    name_ms: str | None = None


@dataclass
class Measurement:
    class_id: str
    class_name_en: str
    measure: str
    quantity: float        # WORLD units: m², m, or count. THE ONLY PLACE quantity is computed.
    unit: str              # "m2" | "m" | "pcs"
    source_ids: list[str]  # candidate ids contributing (traceability for QA)
    confidence: float      # 0..1 — semantics-conditional: 1.0 when the class's
                           #   candidates are self-consistent AND it was purely
                           #   mechanical math after that; 0.5 when the
                           #   semantics list showed mixed evidence; never 1.0
                           #   just because arithmetic was exact.


@dataclass
class TakeoffResult:
    sheet_name: str
    workspace: str         # "m" metering line: "1 trade x 1 sheet"
    measurements: list[Measurement]
    overflowed: bool
    qa: list[str]          # human-review flags, plain English


@dataclass
class SheetData:
    page_w: float
    page_h: float
    paths: list            # fitz get_drawings() output, raw
    words: list            # fitz get_text("words") raw
    png_bytes: bytes       # 200 DPI render
