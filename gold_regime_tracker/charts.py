"""Self-contained inline-SVG price chart (no JS libraries, no external assets).

Draws the close series, the log-regression trend with its ±kσ channel (sampled
as curves, since the bounds fan out multiplicatively in price space), and the
real swing support/resistance + all-time-high levels from ``analysis``. No
rolling σ-band is ever labelled "support" or "resistance".
"""

from __future__ import annotations

import html
from datetime import datetime
from typing import Sequence

from .analysis import SwingLevels, TrendChannel
from .models import PriceBar

_W, _H = 880, 360
_PAD_L, _PAD_R, _PAD_T, _PAD_B = 58, 20, 16, 28


def _esc(v) -> str:
    return html.escape(str(v), quote=True)


def _nice_ticks(lo: float, hi: float, count: int = 5) -> list[float]:
    if hi <= lo:
        return [lo]
    raw = (hi - lo) / count
    mag = 10 ** (len(str(int(raw))) - 1) if raw >= 1 else 1
    step = max(mag, round(raw / mag) * mag)
    ticks, v = [], (int(lo / step)) * step
    while v <= hi + step:
        if v >= lo - step:
            ticks.append(round(v))
        v += step
    return ticks


def render_price_chart(
    bars: Sequence[PriceBar],
    ch: TrendChannel | None,
    swings: SwingLevels | None = None,
    accent: str = "#c9a14a",
) -> str:
    pts = [(i, b) for i, b in enumerate(bars) if b.close is not None]
    if len(pts) < 2:
        return '<div class="chart-empty">Not enough price history to chart.</div>'

    closes = [b.close for _, b in pts]
    last_i = pts[-1][0]

    hi = max(closes)
    lo = min(closes)
    if ch is not None:
        hi = max(hi, ch.upper_at(0), ch.upper_at(last_i))
        lo = min(lo, ch.lower_at(0), ch.lower_at(last_i))
    pad = (hi - lo) * 0.07 or 1
    y_hi, y_lo = hi + pad, lo - pad

    plot_w = _W - _PAD_L - _PAD_R
    plot_h = _H - _PAD_T - _PAD_B

    def px(i: float) -> float:
        return _PAD_L + (i / last_i) * plot_w if last_i else _PAD_L

    def py(v: float) -> float:
        return _PAD_T + (y_hi - v) / (y_hi - y_lo) * plot_h

    svg = [
        f'<svg viewBox="0 0 {_W} {_H}" class="price-chart" '
        f'preserveAspectRatio="xMidYMid meet" role="img" '
        f'aria-label="Gold weekly close with secular trend channel and swing levels">'
    ]

    # Y grid + labels
    for t in _nice_ticks(y_lo, y_hi, 5):
        y = py(t)
        svg.append(f'<line class="grid" x1="{_PAD_L}" y1="{y:.1f}" x2="{_W-_PAD_R}" y2="{y:.1f}"/>')
        svg.append(f'<text class="ylab" x="{_PAD_L-8}" y="{y+4:.1f}">{int(t):,}</text>')

    # Channel as sampled curves (multiplicative fan in price space)
    if ch is not None:
        steps = 60
        idxs = [last_i * s / steps for s in range(steps + 1)]
        up = " ".join(f'{"M" if j==0 else "L"} {px(i):.1f} {py(ch.upper_at(i)):.1f}' for j, i in enumerate(idxs))
        lo_ = " ".join(f'L {px(i):.1f} {py(ch.lower_at(i)):.1f}' for i in reversed(idxs))
        svg.append(f'<path class="band" d="{up} {lo_} Z"/>')
        tr = " ".join(f'{"M" if j==0 else "L"} {px(i):.1f} {py(ch.trend_at(i)):.1f}' for j, i in enumerate(idxs))
        svg.append(f'<path class="trend" d="{tr}"/>')
        ub = " ".join(f'{"M" if j==0 else "L"} {px(i):.1f} {py(ch.upper_at(i)):.1f}' for j, i in enumerate(idxs))
        lb = " ".join(f'{"M" if j==0 else "L"} {px(i):.1f} {py(ch.lower_at(i)):.1f}' for j, i in enumerate(idxs))
        svg.append(f'<path class="bound" d="{ub}"/><path class="bound" d="{lb}"/>')

    # Swing support / resistance + ATH (real levels, labelled with their date).
    # Labels sit inside the plot, right-aligned; coincident levels are de-duped
    # (e.g. when the nearest resistance IS the all-time high).
    if swings is not None:
        drawn: list[float] = []
        tol = (y_hi - y_lo) * 0.02
        for lvl, cls, tag in (
            (swings.all_time_high, "ath", "ATH"),
            (swings.nearest_resistance, "res", "resistance"),
            (swings.nearest_support, "sup", "support"),
        ):
            if not lvl or not (y_lo <= lvl[1] <= y_hi):
                continue
            d, price = lvl
            if any(abs(price - p) < tol for p in drawn):
                continue
            drawn.append(price)
            y = py(price)
            ly = min(max(_PAD_T + 12, y - 6), _H - _PAD_B - 4)
            svg.append(f'<line class="lvl {cls}" x1="{_PAD_L}" y1="{y:.1f}" x2="{_W-_PAD_R}" y2="{y:.1f}"/>')
            svg.append(
                f'<text class="lvllab {cls}" x="{_W-_PAD_R-6}" y="{ly:.1f}">'
                f'{_esc(tag)} ${int(price):,}<tspan class="lvldate"> · {_esc(d[:7])}</tspan></text>'
            )

    # X year labels
    seen = set()
    for i, b in pts:
        try:
            yr = datetime.strptime(b.date, "%Y-%m-%d").year
        except Exception:
            continue
        if yr not in seen:
            seen.add(yr)
            svg.append(f'<text class="xlab" x="{px(i):.1f}" y="{_H-8}">{yr}</text>')

    # Price line + last marker
    d = " ".join(f'{"M" if k==0 else "L"} {px(i):.1f} {py(b.close):.1f}' for k, (i, b) in enumerate(pts))
    svg.append(f'<path class="price" d="{d}" style="stroke:{accent}"/>')
    svg.append(f'<circle class="last" cx="{px(last_i):.1f}" cy="{py(closes[-1]):.1f}" r="3.6" style="fill:{accent}"/>')

    svg.append("</svg>")
    return "".join(svg)
