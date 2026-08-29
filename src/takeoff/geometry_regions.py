"""Closed-region extraction from PDF vector linework.

Two paths (both feed area measurement):
- fills: solidly-filled paths become polygons directly (asphalt pad etc.)
- polygonize: closed stroke rings become polygons via GEOS polygonize
  (JKR hatch/double-line bounded regions, legends, playlot rings).
Core import: shapely. Coordinates stay in PDF points.
"""
import shapely.ops
from shapely.geometry import LineString, Polygon

from .models import CandidateRegion, SheetData

# fraction of the page rect a candidate ring's bbox must cover to be the
# sheet border/frame and be filtered out
FRAME_COVERAGE = 0.95


def _rect_corners(rect):  # fitz.Rect -> 4-corner ring (CCW-ish, what fitz emits)
    return [(rect.x0, rect.y0), (rect.x1, rect.y0), (rect.x1, rect.y1), (rect.x0, rect.y1)]


def _bezier_samples(p0, c1, c2, p1, n=8):
    """Sample a cubic Bezier at t = 0, 1/n, ..., 1 -> n+1 points.

    Same sampler as the fixture's ground truth (tests/fixtures.py), so
    measurements are consistent with the oracle.
    """
    pts = []
    for i in range(n + 1):
        t = i / n
        u = 1.0 - t
        x = (u * u * u * p0[0] + 3 * u * u * t * c1[0]
             + 3 * u * t * t * c2[0] + t * t * t * p1[0])
        y = (u * u * u * p0[1] + 3 * u * u * t * c1[1]
             + 3 * u * t * t * c2[1] + t * t * t * p1[1])
        pts.append((x, y))
    return pts


def _shapely_polygon(coords):
    """coords -> Polygon; auto-close, heal invalid, reduce MultiPolygon to largest."""
    # drop consecutive duplicate vertices (drawing join points repeat)
    deduped = [coords[0]]
    for p in coords[1:]:
        if p != deduped[-1]:
            deduped.append(p)
    if len(deduped) < 3:
        return None
    poly = Polygon(deduped)
    if not poly.is_valid:
        poly = poly.buffer(0)
    if poly.is_empty:
        return None
    if poly.geom_type == "MultiPolygon":
        poly = max(poly.geoms, key=lambda g: g.area)
    if poly.geom_type != "Polygon":
        return None
    return poly


def _walk_items(items):
    """fitz drawing items -> ring coords: l -> end points, re -> 4 corners,
    c -> sampled Bezier, closePath respected (ring auto-closes anyway)."""
    pts = []
    for it in items:
        kind = it[0]
        if kind == "l":
            pts.append((it[1].x, it[1].y))
            pts.append((it[2].x, it[2].y))
        elif kind == "re":
            pts.extend(_rect_corners(it[1]))  # ("re", fitz.Rect, count)
        elif kind == "c":
            pts.extend(_bezier_samples((it[1].x, it[1].y), (it[2].x, it[2].y),
                                       (it[3].x, it[3].y), (it[4].x, it[4].y)))
        # ("closePath", ...) needs no action: Polygon() closes the ring
    return pts


def regions_from_fills(sheet: SheetData, min_area_pt2: float = 0.5) -> list[CandidateRegion]:
    """Solid-filled paths -> CandidateRegions (source="fill"), ids R0.. sequential in path order."""
    out = []
    for path in sheet.paths:
        if path.get("type") not in ("f", "fs") or path.get("fill") is None:
            continue
        poly = _shapely_polygon(_walk_items(path.get("items", [])))
        if poly is None or poly.area < min_area_pt2:
            continue
        out.append(CandidateRegion(
            id=f"R{len(out)}", polygon=poly, bbox=poly.bounds,
            area_pt2=poly.area, fill_rgb=path["fill"], source="fill",
        ))
    return out


def regions_from_polygonize(sheet: SheetData, min_area_pt2: float = 5.0) -> list[CandidateRegion]:
    """Closed stroke rings -> CandidateRegions (source="polygonize").

    Every stroked line/curve/rect edge becomes a LineString; GEOS
    polygonize_full finds the closed faces. Page frame (bbox covering ~>=
    FRAME_COVERAGE of the page rect) is filtered; ids continue the fills
    sequence.
    """
    segs = []
    for path in sheet.paths:
        if path.get("type") not in ("s", "fs") or path.get("color") is None:
            continue
        for it in path.get("items", []):
            if it[0] == "l":
                segs.append(LineString([(it[1].x, it[1].y), (it[2].x, it[2].y)]))
            elif it[0] == "re":
                c = _rect_corners(it[1])
                segs.append(LineString(c + [c[0]]))  # rect edges as a closed ring
            elif it[0] == "c":
                segs.append(LineString(_bezier_samples(
                    (it[1].x, it[1].y), (it[2].x, it[2].y),
                    (it[3].x, it[3].y), (it[4].x, it[4].y))))
    if not segs:
        return []
    polygons, _cuts, _dangles, _invalids = shapely.ops.polygonize_full(segs)

    id_start = len(regions_from_fills(sheet))  # ids continue the fills sequence
    out = []
    for poly in polygons.geoms:  # shapely 2.x: GeometryCollection, iterate .geoms
        if poly.area < min_area_pt2:
            continue
        x0, y0, x1, y1 = poly.bounds
        if x1 - x0 >= FRAME_COVERAGE * sheet.page_w and y1 - y0 >= FRAME_COVERAGE * sheet.page_h:
            continue  # sheet border / frame ring
        out.append(CandidateRegion(
            id=f"R{id_start + len(out)}", polygon=poly, bbox=poly.bounds,
            area_pt2=poly.area, fill_rgb=None, source="polygonize",
        ))
    return out
