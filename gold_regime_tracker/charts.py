"""Self-contained inline-SVG price chart (no JS libraries, no external assets).

Draws the close series over the lookback window, the regression trend line, and
the shaded upper/lower bound channel from ``analysis.linear_channel``. Optional
horizontal reference levels (support / resistance / 200DMA) from config are
overlaid. Pure string building so the result drops straight into the static
page and renders offline / on Cloudflare Pages.
"""

from __future__ import annotations

import html
from datetime import datetime
from typing import Sequence

from .analysis import ChannelAnalysis
from .models import PriceBar

# Canvas geometry
_W, _H = 880, 340
_PAD_L, _PAD_R, _PAD_T, _PAD_B = 56, 18, 18, 28


def _esc(v) -> str:
    return html.escape(str(v), quote=True)


def _nice_ticks(lo: float, hi: float, count: int = 5) -> list[float]:
    if hi <= lo:
        return [lo]
    raw = (hi - lo) / count
    mag = 10 ** (len(str(int(raw))) - 1) if raw >= 1 else 1
    step = max(mag, round(raw / mag) * mag)
    start = (int(lo / step)) * step
    ticks = []
    v = start
    while v <= hi + step:
        if v >= lo - step:
            ticks.append(round(v))
        v += step
    return ticks


def render_price_chart(
    bars: Sequence[PriceBar],
    ch: ChannelAnalysis | None,
    reference_levels: dict | None = None,
    accent: str = "#c9a14a",
) -> str:
    pts = [(i, b) for i, b in enumerate(bars) if b.close is not None]
    if len(pts) < 2:
        return '<div class="chart-empty">Not enough price history to chart.</div>'

    closes = [b.close for _, b in pts]
    n = len(pts)
    last_i = pts[-1][0]

    series_max = max(closes)
    series_min = min(closes)
    if ch is not None:
        series_max = max(series_max, ch.upper_at(0), ch.upper_at(last_i))
        series_min = min(series_min, ch.lower_at(0), ch.lower_at(last_i))
    pad = (series_max - series_min) * 0.08 or 1
    y_hi, y_lo = series_max + pad, series_min - pad

    plot_w = _W - _PAD_L - _PAD_R
    plot_h = _H - _PAD_T - _PAD_B

    def px(i: float) -> float:
        return _PAD_L + (i / last_i) * plot_w if last_i else _PAD_L

    def py(v: float) -> float:
        return _PAD_T + (y_hi - v) / (y_hi - y_lo) * plot_h

    # Y gridlines + labels
    grid = []
    for t in _nice_ticks(y_lo, y_hi, 5):
        y = py(t)
        grid.append(f'<line class="grid" x1="{_PAD_L}" y1="{y:.1f}" x2="{_W-_PAD_R}" y2="{y:.1f}"/>')
        grid.append(f'<text class="ylab" x="{_PAD_L-8}" y="{y+4:.1f}">{int(t):,}</text>')

    # X year labels
    xlabels = []
    seen = set()
    for i, b in pts:
        try:
            yr = datetime.strptime(b.date, "%Y-%m-%d").year
        except Exception:
            continue
        if yr not in seen:
            seen.add(yr)
            x = px(i)
            xlabels.append(f'<text class="xlab" x="{x:.1f}" y="{_H-8}">{yr}</text>')

    svg = [
        f'<svg viewBox="0 0 {_W} {_H}" class="price-chart" '
        f'preserveAspectRatio="xMidYMid meet" role="img" '
        f'aria-label="Gold close with 3-year regression channel">'
    ]
    svg.append("".join(grid))

    # Channel band + trend
    if ch is not None:
        ux0, ux1 = px(0), px(last_i)
        band = (
            f'M {ux0:.1f} {py(ch.upper_at(0)):.1f} L {ux1:.1f} {py(ch.upper_at(last_i)):.1f} '
            f'L {ux1:.1f} {py(ch.lower_at(last_i)):.1f} L {ux0:.1f} {py(ch.lower_at(0)):.1f} Z'
        )
        svg.append(f'<path class="band" d="{band}"/>')
        svg.append(
            f'<line class="bound" x1="{ux0:.1f}" y1="{py(ch.upper_at(0)):.1f}" '
            f'x2="{ux1:.1f}" y2="{py(ch.upper_at(last_i)):.1f}"/>'
        )
        svg.append(
            f'<line class="bound" x1="{ux0:.1f}" y1="{py(ch.lower_at(0)):.1f}" '
            f'x2="{ux1:.1f}" y2="{py(ch.lower_at(last_i)):.1f}"/>'
        )
        svg.append(
            f'<line class="trend" x1="{ux0:.1f}" y1="{py(ch.trend_at(0)):.1f}" '
            f'x2="{ux1:.1f}" y2="{py(ch.trend_at(last_i)):.1f}"/>'
        )

    # Reference levels (faint, labelled)
    if reference_levels:
        for label, key in (
            ("resistance", "resistance_high"),
            ("support", "support_shelf"),
            ("200DMA", "price_200dma"),
        ):
            lvl = reference_levels.get(key)
            if lvl is None or not (y_lo <= lvl <= y_hi):
                continue
            y = py(lvl)
            svg.append(f'<line class="ref" x1="{_PAD_L}" y1="{y:.1f}" x2="{_W-_PAD_R}" y2="{y:.1f}"/>')
            svg.append(f'<text class="reflab" x="{_W-_PAD_R-4}" y="{y-4:.1f}">{_esc(label)} {int(lvl):,}</text>')

    # Price line
    d = " ".join(
        f'{"M" if k == 0 else "L"} {px(i):.1f} {py(b.close):.1f}' for k, (i, b) in enumerate(pts)
    )
    svg.append(f'<path class="price" d="{d}" style="stroke:{accent}"/>')

    # Last-point marker
    lx, ly = px(last_i), py(closes[-1])
    svg.append(f'<circle class="last" cx="{lx:.1f}" cy="{ly:.1f}" r="3.5" style="fill:{accent}"/>')

    svg.append("".join(xlabels))
    svg.append("</svg>")
    return "".join(svg)
