# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""SVG drawing of a laid-out figure, and its PNG rendering (DD-254).

One convention for line ends, tested on its own: ``card_a`` is *how many A per one B* and is
drawn at A's end. The glyphs are the information-engineering ones -- the mark nearest the
box is the maximum (bar = one, crow's foot = many), the outer mark the minimum (bar = one,
circle = zero):

- ``1``  two bars           exactly one
- ``01`` bar + circle       zero or one
- ``1n`` crow + bar         one or more
- ``0n`` crow + circle      zero or more

The SVG text is deterministic: coordinates are rounded and elements are written in a fixed
order. Rasterising goes through a headless Chromium browser at device scale 2.
"""

from __future__ import annotations

import math
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional
from xml.sax.saxutils import escape

from .layout import (
    DOMAIN_HEIGHT,
    FONT_SCALE,
    LABEL_SIZE,
    LEGEND_CELL,
    LEGEND_ROW,
    LINE_HEIGHT,
    TITLE_HEIGHT,
    FigureLayout,
    Point,
)

NAVY = "#1F3864"
CORE_FILL = "#DCE6F2"
EXTERNAL_FILL = "#EEEEEE"
EXTERNAL_STROKE = "#8C8C8C"
GAP_STROKE = "#C0504D"
FONT = "Segoe UI, Arial, sans-serif"

CARDINALITIES = ("1", "01", "1n", "0n")
CARDINALITY_MEANING = {
    "1": "exactly one",
    "01": "zero or one",
    "1n": "one or more",
    "0n": "zero or more",
}


def _n(value: float) -> str:
    text = f"{value:.1f}"
    return text[:-2] if text.endswith(".0") else text


def _unit(p: Point, q: Point) -> tuple[float, float]:
    dx, dy = q[0] - p[0], q[1] - p[1]
    length = math.hypot(dx, dy) or 1.0
    return dx / length, dy / length


def end_marks(p: Point, q: Point, card: str) -> list[tuple[str, tuple]]:
    """Primitive marks for line end *card* at *p*, for a line arriving from *q*.

    Returns ``[("line", (x1, y1, x2, y2)) | ("circle", (cx, cy, r))]``: the geometry the
    SVG and the crow's-foot tests both read.
    """
    if card not in CARDINALITIES:
        raise ValueError(f"unknown cardinality {card!r}")
    ux, uy = _unit(p, q)
    px, py = -uy, ux  # perpendicular

    def at(d: float) -> Point:
        return p[0] + ux * d, p[1] + uy * d

    def bar(d: float) -> tuple[str, tuple]:
        cx, cy = at(d)
        return "line", (cx + px * 7, cy + py * 7, cx - px * 7, cy - py * 7)

    def circle(d: float) -> tuple[str, tuple]:
        cx, cy = at(d)
        return "circle", (cx, cy, 5.0)

    marks: list[tuple[str, tuple]] = []
    if card in ("1n", "0n"):
        tip = at(14)
        marks += [
            ("line", (tip[0], tip[1], p[0] + px * 8, p[1] + py * 8)),
            ("line", (tip[0], tip[1], p[0], p[1])),
            ("line", (tip[0], tip[1], p[0] - px * 8, p[1] - py * 8)),
        ]
    else:
        marks.append(bar(8))
    marks.append(circle(24) if card in ("01", "0n") else bar(20))
    return marks


def _marks_svg(marks: list[tuple[str, tuple]], stroke: str) -> list[str]:
    out = []
    for kind, geometry in marks:
        if kind == "line":
            x1, y1, x2, y2 = geometry
            out.append(
                f'<line x1="{_n(x1)}" y1="{_n(y1)}" x2="{_n(x2)}" y2="{_n(y2)}" '
                f'stroke="{stroke}" stroke-width="1.6"/>'
            )
        else:
            cx, cy, r = geometry
            out.append(
                f'<circle cx="{_n(cx)}" cy="{_n(cy)}" r="{_n(r)}" fill="white" '
                f'stroke="{stroke}" stroke-width="1.6"/>'
            )
    return out


def _text(x: float, y: float, text: str, size: float, **attrs: str) -> str:
    extra = "".join(f' {k.replace("_", "-")}="{v}"' for k, v in attrs.items())
    return f'<text x="{_n(x)}" y="{_n(y)}" font-size="{_n(size)}"{extra}>{escape(text)}</text>'


def render_svg(figure: FigureLayout) -> str:
    """The SVG document of *figure*."""
    w, h = figure.width, figure.height
    out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{_n(w)}" height="{_n(h)}" '
        f'viewBox="0 0 {_n(w)} {_n(h)}" font-family="{FONT}">',
        f'<rect x="0" y="0" width="{_n(w)}" height="{_n(h)}" fill="white"/>',
    ]
    # Links first, so boxes sit on top of their line ends' roots.
    for edge in figure.edges:
        stroke = GAP_STROKE if edge.link.dashed else "#404040"
        dash = ' stroke-dasharray="6 4"' if edge.link.dashed else ""
        pts = " ".join(f"{_n(x)},{_n(y)}" for x, y in edge.points)
        out.append(
            f'<polyline points="{pts}" fill="none" stroke="{stroke}" stroke-width="1.4"{dash}/>'
        )
        if edge.link.card_a:
            out += _marks_svg(end_marks(edge.points[0], edge.points[1], edge.link.card_a), stroke)
        if edge.link.card_b:
            out += _marks_svg(end_marks(edge.points[-1], edge.points[-2], edge.link.card_b), stroke)
    for edge in figure.edges:
        if edge.label_box and edge.link.label:
            x, y, bw, bh = edge.label_box
            out.append(
                _text(
                    x + bw / 2,
                    y + bh - 5.0,
                    edge.link.label,
                    LABEL_SIZE,
                    text_anchor="middle",
                    fill="#202020",
                    stroke="white",
                    stroke_width="4",
                    paint_order="stroke",
                    font_style="italic",
                )
            )
    for box in figure.boxes:
        node = box.node
        if node.kind == "external":
            fill, stroke, dash = EXTERNAL_FILL, EXTERNAL_STROKE, ""
        elif node.kind == "gap":
            fill, stroke, dash = "white", GAP_STROKE, ' stroke-dasharray="6 4"'
        else:
            fill, stroke, dash = CORE_FILL, NAVY, ""
        out.append(
            f'<rect x="{_n(box.x)}" y="{_n(box.y)}" width="{_n(box.w)}" height="{_n(box.h)}" '
            f'rx="8" ry="8" fill="{fill}" stroke="{stroke}" stroke-width="1.6"{dash}/>'
        )
        if node.kind != "gap":
            out.append(
                f'<path d="M{_n(box.x)},{_n(box.y + TITLE_HEIGHT)} V{_n(box.y + 8)} '
                f"Q{_n(box.x)},{_n(box.y)} {_n(box.x + 8)},{_n(box.y)} H{_n(box.right - 8)} "
                f"Q{_n(box.right)},{_n(box.y)} {_n(box.right)},{_n(box.y + 8)} "
                f'V{_n(box.y + TITLE_HEIGHT)} Z" fill="{stroke}"/>'
            )
        title_fill = GAP_STROKE if node.kind == "gap" else "white"
        out.append(
            _text(
                box.x + box.w / 2,
                box.y + 20.0,
                node.title,
                13.0 * FONT_SCALE,
                text_anchor="middle",
                font_weight="bold",
                fill=title_fill,
            )
        )
        y = box.y + TITLE_HEIGHT + 16.0
        if node.domain:
            out.append(
                _text(
                    box.x + box.w / 2,
                    y,
                    node.domain,
                    10.0 * FONT_SCALE,
                    text_anchor="middle",
                    font_style="italic",
                    fill="#505050",
                )
            )
            y += DOMAIN_HEIGHT
        for line in node.lines:
            out.append(_text(box.x + 10.0, y, line, 10.5 * FONT_SCALE, fill="#202020"))
            y += LINE_HEIGHT
    if figure.legend_y is not None:
        out += _legend(24.0, figure.legend_y + 6.0, figure.legend_columns)
    out.append("</svg>")
    return "\n".join(out) + "\n"


def _legend(x: float, y: float, columns: int = 4) -> list[str]:
    """ "How to read the line ends": one sample per cardinality, *columns* to a row."""
    out = [
        _text(
            x,
            y + 12.0,
            "How to read the line ends",
            10.5 * FONT_SCALE,
            font_weight="bold",
            fill=NAVY,
        )
    ]
    for position, card in enumerate(CARDINALITIES):
        left = x + (position % columns) * LEGEND_CELL
        row_y = y + 40.0 + (position // columns) * LEGEND_ROW
        p, q = (left, row_y), (left + 60.0, row_y)
        out.append(
            f'<line x1="{_n(p[0])}" y1="{_n(p[1])}" x2="{_n(q[0])}" y2="{_n(q[1])}" '
            'stroke="#404040" stroke-width="1.4"/>'
        )
        out += _marks_svg(end_marks(p, q, card), "#404040")
        out.append(
            _text(
                q[0] + 8.0, q[1] + 4.0, CARDINALITY_MEANING[card], 10.0 * FONT_SCALE, fill="#202020"
            )
        )
    return out


# --------------------------------------------------------------------------------------
# PNG rendering through a headless Chromium browser.
# --------------------------------------------------------------------------------------
_BROWSER_NAMES = (
    "chrome",
    "google-chrome",
    "google-chrome-stable",
    "chromium",
    "chromium-browser",
    "msedge",
    "microsoft-edge",
)
_WINDOWS_BROWSERS = (
    r"Google\Chrome\Application\chrome.exe",
    r"Microsoft\Edge\Application\msedge.exe",
)


def find_browser() -> Optional[str]:
    """A headless-capable Chromium executable, or ``None``. ``KAIROS_CHROME`` overrides."""
    override = os.environ.get("KAIROS_CHROME")
    if override:
        return override if Path(override).is_file() else None
    for name in _BROWSER_NAMES:
        found = shutil.which(name)
        if found:
            return found
    for base in (
        os.environ.get("PROGRAMFILES"),
        os.environ.get("PROGRAMFILES(X86)"),
        os.environ.get("LOCALAPPDATA"),
    ):
        for relative in _WINDOWS_BROWSERS:
            if base and (Path(base) / relative).is_file():
                return str(Path(base) / relative)
    mac = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    return str(mac) if mac.is_file() else None


def svg_to_png(svg: str, width: float, height: float, browser: str) -> bytes:
    """Rasterise *svg* at device scale 2 with *browser*; ``RuntimeError`` on failure."""
    with tempfile.TemporaryDirectory(prefix="kairos-business-doc-") as tmp:
        page = Path(tmp) / "figure.html"
        png = Path(tmp) / "figure.png"
        page.write_text(
            "<!DOCTYPE html><html><head><meta charset='utf-8'><style>"
            "html,body{margin:0;padding:0;background:white}</style></head><body>"
            + svg.split("?>", 1)[-1]
            + "</body></html>",
            encoding="utf-8",
        )
        command = [
            browser,
            "--headless",
            "--disable-gpu",
            "--hide-scrollbars",
            "--force-device-scale-factor=2",
            f"--window-size={math.ceil(width)},{math.ceil(height)}",
            f"--screenshot={png}",
            page.as_uri(),
        ]
        try:
            subprocess.run(command, check=True, capture_output=True, timeout=90)
        except (OSError, subprocess.SubprocessError) as exc:
            raise RuntimeError(f"headless browser failed: {exc}") from exc
        if not png.is_file():
            raise RuntimeError("headless browser wrote no screenshot")
        return png.read_bytes()
