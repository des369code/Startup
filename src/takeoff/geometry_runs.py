"""Polyline-run extraction from PDF stroke linework.

Connected chains of stroke segments (open polylines) are run candidates —
the length side of the takeoff engine. Closed rings are excluded by default:
a closed chain's total length is a PERIMETER (both sides + end caps of a
drain, the full outline of a double-line kerb), a wrong measurement, not a
run. The same ring is already a region candidate via polygonize, so nothing
is lost. Coordinates stay in PDF points.
"""
from . import geometry_regions
from .models import CandidateRun, SheetData

# endpoint-merging tolerance: drawing joints are sloppy at sub-point scale
UNION_TOL_PT = 1.5


def _segments(path):
    """fitz drawing items -> list of (p0, p1) endpoint pairs.

    ("c", p1, c1, c2, p2) is sampled into 8 chords with the same cubic
    sampler as the fixture's ground truth, so run lengths are consistent
    with the oracle. ("re", ...) rects and ("qu", ...) quads are ignored:
    their 4 perimeter segments are ring/sideband edges, not run strokes.
    """
    segs = []
    for it in path.get("items", []):
        kind = it[0]
        if kind == "l":
            segs.append(((it[1].x, it[1].y), (it[2].x, it[2].y)))
        elif kind == "c":
            pts = geometry_regions._bezier_samples(
                (it[1].x, it[1].y), (it[2].x, it[2].y),
                (it[3].x, it[3].y), (it[4].x, it[4].y),
            )
            segs.extend(zip(pts, pts[1:]))
    return segs


def _canonical_coords(segs, tol):
    """Segment endpoints -> (canonical coords, node-pair segments).

    Endpoints within `tol` of an existing canonical point snap to it
    (nearest match); segments whose endpoints snap to the SAME node are
    degenerate (zero-length) and dropped.
    """
    coords = []  # canonical endpoint coords (node id == index)

    def node_for(p):
        best, best_d2 = None, tol * tol
        for i, q in enumerate(coords):
            d2 = (q[0] - p[0]) ** 2 + (q[1] - p[1]) ** 2
            if d2 <= best_d2:
                best, best_d2 = i, d2
        if best is None:
            coords.append((p[0], p[1]))
            return len(coords) - 1
        return best

    nodes = []
    for a, b in segs:
        na, nb = node_for(a), node_for(b)
        if na != nb:
            nodes.append((na, nb))
    return coords, nodes


def _component_chains(edges):
    """node-pair edges -> list of (points, closed) chains.

    Union-find splits edges into components; each component is then walked
    edge-by-edge. Open chains start at a degree-1 endpoint. Components with
    no degree-1 node are cycles -> closed (the points loop back to start).
    ponytail: O(n^2) endpoint snap; forked components are split at the fork
    (a walk consumes the first unvisited edge at every node) — no fork
    appears in the fixtures, noted for the real-sheet case.
    """
    parent = {}

    def find(a):
        parent.setdefault(a, a)
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for a, b in edges:
        find(a)
        find(b)
        union(a, b)

    comp = {}  # root -> list of nodes
    for n in parent:
        comp.setdefault(find(n), []).append(n)

    adj = {n: [] for n in parent}
    for i, (a, b) in enumerate(edges):
        adj[a].append((b, i))
        adj[b].append((a, i))

    chains = []  # (node-id walk, closed)
    for root, nodes in comp.items():
        done = set()
        # open chains first, from unused degree-1 endpoints
        opened = True
        while opened:
            opened = False
            starts = [n for n in nodes
                      if not any(e in done for _, e in adj[n])
                      and sum(1 for _, e in adj[n] if e not in done) == 1]
            if starts:
                cur = starts[0]
                walk = [cur]
                while True:
                    nxt = None
                    for nb, e in adj[cur]:
                        if e not in done:
                            nxt, ee = nb, e
                            break
                    if nxt is None:
                        break
                    done.add(ee)
                    walk.append(nxt)
                    cur = nxt
                chains.append((walk, False))
                opened = True
        # leftover: closed walks from any node with unused edges
        while True:
            start = None
            for n in nodes:
                if any(e not in done for _, e in adj[n]):
                    start = n
                    break
            if start is None:
                break
            walk = [start]
            cur = start
            while True:
                nxt = None
                for nb, e in adj[cur]:
                    if e not in done:
                        nxt, ee = nb, e
                        break
                if nxt is None:
                    break
                done.add(ee)
                walk.append(nxt)
                cur = nxt
                if nxt == start and all(e in done for _, e in adj[start]):
                    break
            chains.append((walk, True))
    return chains


def runs_from_strokes(sheet: SheetData, min_length_pt: float = 1.0,
                      exclude_closed: bool = True) -> list[CandidateRun]:
    """Stroke chains -> CandidateRuns (ids RUN0.. in drawing order).

    Rules: stroke items only (type in ("s", "fs"), color set); segment ops
    l / sampled-c; re/qu ignored. Chains with no degree-1 endpoint are
    closed rings and are dropped unless exclude_closed=False (then they are
    returned with closed=True). Chains shorter than min_length_pt dropped.
    """
    segs = []
    for path in sheet.paths:
        if path.get("type") not in ("s", "fs") or path.get("color") is None:
            continue
        segs.extend(_segments(path))
    if not segs:
        return []

    coords, edges = _canonical_coords(segs, UNION_TOL_PT)
    runs = []
    for walk, closed in _component_chains(edges):
        if closed and exclude_closed:
            continue  # perimeter is not a run length
        pts = [coords[i] for i in walk]
        length = sum(
            ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5
            for a, b in zip(pts, pts[1:])
        )
        if length < min_length_pt:
            continue
        xs, ys = zip(*pts)
        runs.append(CandidateRun(
            id=f"RUN{len(runs)}", points=pts, length_pt=length,
            bbox=(min(xs), min(ys), max(xs), max(ys)), closed=closed,
        ))
    return runs
