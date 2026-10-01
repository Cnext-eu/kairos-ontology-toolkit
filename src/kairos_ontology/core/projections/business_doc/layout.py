# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Deterministic placement of entity boxes and orthogonal links for one figure (DD-254).

Three columns. The figure's core entities stand in the centre column in the order given;
the other entities alternate left and right, ordered by how many links they have and then by
key, each pulled level with the first centre box it links to. Links are orthogonal:

- centre and side box: out of the facing sides, through a vertical lane in the gap;
- two boxes in the same column: out of the outer side, through a lane in the outer gutter
  (the centre column uses the right gap);
- left box and right box: around the bottom, through the outer gutters and a bottom lane.

Each lane holds one link, so no two vertical runs share an x. Labels go on the longest
horizontal run at the first slot that overlaps neither a box nor another label. The same
input always yields the same coordinates.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

BOX_WIDTH = 230.0
COLUMN_GAP = 300.0
OUTER_GUTTER = 70.0
MARGIN = 24.0
ROW_GAP = 46.0
BOTTOM_LANE_GAP = 22.0
FONT_SCALE = 1.15
TITLE_HEIGHT = 30.0
LINE_HEIGHT = 20.0
DOMAIN_HEIGHT = 18.0
LABEL_SIZE = 10.0 * FONT_SCALE
LEGEND_HEIGHT = 74.0
LEGEND_ROW = 34.0
LEGEND_CELL = 210.0
ANCHOR_PITCH = 26.0  # vertical room per line end on a box side

Point = tuple[float, float]


@dataclass(frozen=True)
class NodeSpec:
    key: str
    title: str
    domain: Optional[str] = None
    lines: tuple[str, ...] = ()
    kind: str = "core"  # core | external | gap


@dataclass(frozen=True)
class LinkSpec:
    key: str
    a: str
    b: str
    card_a: Optional[str]  # how many A per one B, drawn at A's end
    card_b: Optional[str]  # how many B per one A, drawn at B's end
    label: str = ""
    dashed: bool = False


@dataclass(frozen=True)
class Box:
    key: str
    x: float
    y: float
    w: float
    h: float
    node: NodeSpec

    @property
    def right(self) -> float:
        return self.x + self.w

    @property
    def bottom(self) -> float:
        return self.y + self.h


@dataclass(frozen=True)
class Edge:
    link: LinkSpec
    points: tuple[Point, ...]
    label_box: Optional[tuple[float, float, float, float]]  # x, y, w, h


@dataclass(frozen=True)
class FigureLayout:
    width: float
    height: float
    boxes: tuple[Box, ...]
    edges: tuple[Edge, ...]
    legend_y: Optional[float]
    legend_columns: int = 4


def box_height(node: NodeSpec) -> float:
    """``46 + 20 per line (+18 with a domain line)``, the reference measurements."""
    return 46.0 + LINE_HEIGHT * len(node.lines) + (DOMAIN_HEIGHT if node.domain else 0.0)


def label_size(text: str) -> tuple[float, float]:
    """Estimated width and height of a link label at the scaled label font."""
    return 0.56 * LABEL_SIZE * len(text) + 8.0, LABEL_SIZE + 6.0


def overlaps(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> bool:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah


def _degree(links: list[LinkSpec]) -> dict[str, int]:
    count: dict[str, int] = {}
    for link in links:
        count[link.a] = count.get(link.a, 0) + 1
        count[link.b] = count.get(link.b, 0) + 1
    return count


def layout_figure(
    nodes: list[NodeSpec], links: list[LinkSpec], *, legend: bool = True
) -> FigureLayout:
    """Place *nodes* and route *links*; deterministic in its inputs."""
    if not nodes:
        raise ValueError("a figure needs at least one entity")
    keys = [node.key for node in nodes]
    if len(set(keys)) != len(keys):
        raise ValueError("figure entity keys must be unique")
    by_key = {node.key: node for node in nodes}
    links = [link for link in links if link.a in by_key and link.b in by_key]
    degree = _degree(links)

    centre = [node for node in nodes if node.kind == "core"]
    if not centre:
        centre = [sorted(nodes, key=lambda n: (-degree.get(n.key, 0), n.key))[0]]
    centre_keys = {node.key for node in centre}
    others = sorted(
        (node for node in nodes if node.key not in centre_keys),
        key=lambda n: (-degree.get(n.key, 0), n.key),
    )
    left = others[0::2]
    right = others[1::2]

    has_left = bool(left)
    x_left = MARGIN + OUTER_GUTTER
    x_centre = x_left + (BOX_WIDTH + COLUMN_GAP if has_left else 0.0)
    x_right = x_centre + BOX_WIDTH + COLUMN_GAP

    def height_of(node: NodeSpec) -> float:
        # Room for every line end on one side, so their marks never touch.
        return max(box_height(node), TITLE_HEIGHT + 12.0 + ANCHOR_PITCH * degree.get(node.key, 0))

    boxes: dict[str, Box] = {}
    top = MARGIN
    y = top
    for node in centre:
        h = height_of(node)
        boxes[node.key] = Box(node.key, x_centre, y, BOX_WIDTH, h, node)
        y += h + ROW_GAP

    def anchor_y(node: NodeSpec) -> float:
        for link in sorted(links, key=lambda lk: lk.key):
            other = link.b if link.a == node.key else link.a if link.b == node.key else None
            if other in boxes and other in centre_keys:
                return boxes[other].y
        return top

    for column, x in ((left, x_left), (right, x_right)):
        cursor = top
        for node in sorted(column, key=lambda n: (anchor_y(n), -degree.get(n.key, 0), n.key)):
            h = height_of(node)
            y = max(cursor, anchor_y(node))
            boxes[node.key] = Box(node.key, x, y, BOX_WIDTH, h, node)
            cursor = y + h + ROW_GAP

    def column_of(key: str) -> str:
        x = boxes[key].x
        return (
            "left"
            if x == x_left and has_left and key not in centre_keys
            else ("centre" if key in centre_keys else "right")
        )

    content_bottom = max(box.bottom for box in boxes.values())
    right_edge = max(box.right for box in boxes.values())

    # ---- channel assignment ------------------------------------------------------------
    gap_lc = (x_left + BOX_WIDTH, x_centre)
    gap_cr = (x_centre + BOX_WIDTH, x_right)
    plans: list[tuple[LinkSpec, str]] = []
    for link in sorted(links, key=lambda lk: lk.key):
        ca, cb = column_of(link.a), column_of(link.b)
        if link.a == link.b:
            channel = "self"
        elif {ca, cb} == {"left", "centre"}:
            channel = "gap_lc"
        elif {ca, cb} == {"centre", "right"} or (ca == cb == "centre"):
            channel = "gap_cr"
        elif ca == cb == "left":
            channel = "outer_left"
        elif ca == cb == "right":
            channel = "outer_right"
        else:
            channel = "around"
        plans.append((link, channel))

    # Side anchors: spread the links leaving one side of one box, ordered by the other end.
    side_links: dict[tuple[str, str], list[tuple[float, str]]] = {}

    def sides(link: LinkSpec, channel: str) -> tuple[str, str]:
        if channel in ("gap_lc", "gap_cr"):
            if link.a in centre_keys and link.b in centre_keys:
                return "right", "right"
            a_side = "right" if boxes[link.a].x < boxes[link.b].x else "left"
            b_side = "left" if a_side == "right" else "right"
            return a_side, b_side
        if channel == "outer_left":
            return "left", "left"
        if channel in ("outer_right", "self"):
            return "right", "right"
        # around: each leaves by its outer side
        return (
            "left" if column_of(link.a) == "left" else "right",
            "left" if column_of(link.b) == "left" else "right",
        )

    link_sides: dict[str, tuple[str, str]] = {}
    for link, channel in plans:
        a_side, b_side = sides(link, channel)
        link_sides[link.key] = (a_side, b_side)
        side_links.setdefault((link.a, a_side), []).append((boxes[link.b].y, link.key + ":a"))
        side_links.setdefault((link.b, b_side), []).append((boxes[link.a].y, link.key + ":b"))
    anchor_frac: dict[str, float] = {}
    for (_key, _side), entries in side_links.items():
        entries.sort()
        for position, (_y, end) in enumerate(entries):
            anchor_frac[end] = (position + 1) / (len(entries) + 1)

    def anchor(key: str, side: str, end: str) -> Point:
        box = boxes[key]
        body_top = box.y + TITLE_HEIGHT
        y = body_top + (box.h - TITLE_HEIGHT) * anchor_frac[end]
        return (box.right if side == "right" else box.x, y)

    # One lane per vertical run. A link routed around the bottom runs down an outer gutter
    # at each end, so it takes a lane in that gutter's pool like a same-column link does.
    lanes: dict[str, list[str]] = {}
    for link, channel in plans:
        if channel == "around":
            a_side, b_side = link_sides[link.key]
            lanes.setdefault(f"outer_{a_side}", []).append(link.key + ":a")
            lanes.setdefault(f"outer_{b_side}", []).append(link.key + ":b")
        lanes.setdefault(channel, []).append(link.key)

    def lane_x(channel: str, key: str) -> float:
        members = lanes[channel]
        n = len(members)
        k = members.index(key)
        if channel in ("gap_lc", "gap_cr"):
            lo, hi = gap_lc if channel == "gap_lc" else gap_cr
            return lo + (hi - lo) * (0.2 + 0.6 * (k + 0.5) / n)
        if channel == "outer_left":
            return x_left - OUTER_GUTTER * (k + 1) / (n + 1)
        return right_edge + OUTER_GUTTER * (k + 1) / (n + 1)

    edges: list[Edge] = []
    bottom_lanes = lanes.get("around", [])
    for link, channel in plans:
        a_side, b_side = link_sides[link.key]
        pa = anchor(link.a, a_side, link.key + ":a")
        pb = anchor(link.b, b_side, link.key + ":b")
        if channel == "self":
            out = boxes[link.a].right + 36.0
            points = (pa, (out, pa[1]), (out, pb[1] + 24.0), (pb[0], pb[1] + 24.0))
        elif channel == "around":
            k = bottom_lanes.index(link.key)
            lane_y = content_bottom + BOTTOM_LANE_GAP * (k + 1)
            xa = lane_x(f"outer_{a_side}", link.key + ":a")
            xb = lane_x(f"outer_{b_side}", link.key + ":b")
            points = (pa, (xa, pa[1]), (xa, lane_y), (xb, lane_y), (xb, pb[1]), pb)
        else:
            lx = lane_x(channel, link.key)
            if (
                abs(pa[1] - pb[1]) < 0.5
                and channel in ("gap_lc", "gap_cr")
                and (link.a not in centre_keys or link.b not in centre_keys)
            ):
                points = (pa, pb)
            else:
                points = (pa, (lx, pa[1]), (lx, pb[1]), pb)
        edges.append(Edge(link, tuple((round(x, 1), round(y, 1)) for x, y in points), None))

    # ---- labels ------------------------------------------------------------------------
    obstacles = [(b.x, b.y, b.w, b.h) for b in boxes.values()]
    # Every line run is an obstacle too: a label must not sit on any line, its own included.
    for edge in edges:
        for (x1, y1), (x2, y2) in zip(edge.points, edge.points[1:]):
            obstacles.append(
                (min(x1, x2) - 1.0, min(y1, y2) - 1.0, abs(x2 - x1) + 2.0, abs(y2 - y1) + 2.0)
            )
    placed: list[tuple[float, float, float, float]] = []
    labelled: list[Edge] = []
    for edge in edges:
        if not edge.link.label:
            labelled.append(edge)
            continue
        w, h = label_size(edge.link.label)
        segments = sorted(
            ((edge.points[i], edge.points[i + 1]) for i in range(len(edge.points) - 1)),
            key=lambda s: -abs(s[1][0] - s[0][0]) - 0.25 * abs(s[1][1] - s[0][1]),
        )
        choice = None
        for p, q in segments:
            for t in (0.5, 0.4, 0.6, 0.3, 0.7, 0.2, 0.8, 0.1, 0.9):
                cx = p[0] + (q[0] - p[0]) * t
                cy = p[1] + (q[1] - p[1]) * t
                for dy in (-h - 3.0, 3.0, -2 * h - 4.0, h + 5.0):
                    if abs(q[1] - p[1]) > abs(q[0] - p[0]):  # vertical run: beside it
                        side = 5.0 if dy > 0 else -w - 5.0
                        candidate = (cx + side, cy - h / 2 + (dy if abs(dy) > h else 0), w, h)
                    else:
                        candidate = (cx - w / 2, cy + dy, w, h)
                    if not any(overlaps(candidate, o) for o in obstacles + placed):
                        choice = candidate
                        break
                if choice:
                    break
            if choice:
                break
        if choice is None:  # nothing free: take the first slot (tests flag it)
            p, q = segments[0]
            choice = ((p[0] + q[0]) / 2 - w / 2, (p[1] + q[1]) / 2 - h - 2.0, w, h)
        choice = tuple(round(v, 1) for v in choice)
        placed.append(choice)
        labelled.append(Edge(edge.link, edge.points, choice))

    xs = [b.right for b in boxes.values()] + [p[0] for e in labelled for p in e.points]
    xs += [lb[0] + lb[2] for e in labelled if (lb := e.label_box)]
    ys = [b.bottom for b in boxes.values()] + [p[1] for e in labelled for p in e.points]
    ys += [lb[1] + lb[3] for e in labelled if (lb := e.label_box)]
    min_x = min(
        [b.x for b in boxes.values()]
        + [p[0] for e in labelled for p in e.points]
        + [lb[0] for e in labelled if (lb := e.label_box)]
    )
    shift = max(0.0, MARGIN - min_x)
    width = max(xs) + MARGIN + shift
    height = max(ys) + MARGIN
    legend_y = None
    legend_columns = 4
    if legend:
        # Four line-end samples in a row when the figure is wide enough, else two by two.
        legend_columns = 4 if width >= 2 * MARGIN + 4 * LEGEND_CELL else 2
        legend_y = round(height, 1)
        height += LEGEND_HEIGHT + (LEGEND_ROW if legend_columns == 2 else 0.0)
    if shift:
        boxes = {k: Box(b.key, b.x + shift, b.y, b.w, b.h, b.node) for k, b in boxes.items()}
        labelled = [
            Edge(
                e.link,
                tuple((round(x + shift, 1), y) for x, y in e.points),
                (round(e.label_box[0] + shift, 1),) + e.label_box[1:] if e.label_box else None,
            )
            for e in labelled
        ]
    return FigureLayout(
        width=round(max(width, 560.0), 1),
        height=round(height, 1),
        boxes=tuple(boxes[key] for key in sorted(boxes)),
        edges=tuple(labelled),
        legend_y=legend_y,
        legend_columns=legend_columns,
    )
