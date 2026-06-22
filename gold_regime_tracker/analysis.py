"""Price-structure analysis for the chart.

Two distinct things, kept deliberately separate because conflating them is
misleading:

1. A **secular trend channel** (``trend_channel``). A least-squares fit of
   log-price vs time, with bounds at trend × e^(±kσ). Log space is used because
   gold roughly doubled over the window — a *linear* fit to a curve produces
   serially-correlated, regime-dependent residuals whose ±2σ bounds carry no
   real tail probability. We still measure that residual autocorrelation and
   **flag the channel as unreliable** when the trend is non-linear, so the page
   never claims the bounds are an actionable level or a clean statistical tail.
   This is good for one thing only: confirming a multi-year uptrend exists.

2. **Swing support/resistance** (``swing_levels``). Actual price pivots — local
   highs and lows where buying/selling clustered. This is what "support" and
   "resistance" really mean, as opposed to a rolling σ-band evaluated at today's
   x-position (which moves every week and is not a level at all).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence

from .models import PriceBar


@dataclass
class TrendChannel:
    n: int
    a: float                 # log-price slope per period
    b: float                 # log-price intercept
    sigma: float             # std dev of log residuals
    k: float
    periods_per_year: float
    last_close: float
    trend_last: float
    upper_last: float
    lower_last: float
    position: float          # last close within [lower=0, upper=1]
    annualized_trend_pct: float
    autocorr: float          # lag-1 autocorrelation of residuals
    reliable: bool           # False => bounds are descriptive only, not a tail
    read: str
    caveat: str = ""

    def trend_at(self, i: float) -> float:
        return math.exp(self.a * i + self.b)

    def upper_at(self, i: float) -> float:
        return math.exp(self.a * i + self.b + self.k * self.sigma)

    def lower_at(self, i: float) -> float:
        return math.exp(self.a * i + self.b - self.k * self.sigma)


def trend_channel(
    bars: Sequence[PriceBar], k: float = 2.0, periods_per_year: float = 52.0
) -> TrendChannel | None:
    pts = [(i, b.close) for i, b in enumerate(bars) if b.close and b.close > 0]
    n = len(pts)
    if n < 8:
        return None

    xs = [i for i, _ in pts]
    ys = [math.log(c) for _, c in pts]
    sx, sy = sum(xs), sum(ys)
    sxx = sum(i * i for i in xs)
    sxy = sum(i * y for i, y in zip(xs, ys))
    denom = n * sxx - sx * sx
    if denom == 0:
        return None
    a = (n * sxy - sx * sy) / denom
    b = (sy - a * sx) / n

    resid = [y - (a * i + b) for i, y in zip(xs, ys)]
    sigma = math.sqrt(sum(r * r for r in resid) / n)

    # Lag-1 autocorrelation of residuals: high => the line is being forced
    # through a bend and the bounds are not a clean statistical tail.
    denom_ac = sum(r * r for r in resid)
    autocorr = (
        sum(resid[t] * resid[t - 1] for t in range(1, n)) / denom_ac if denom_ac else 0.0
    )
    reliable = abs(autocorr) < 0.5

    last_i, last_close = pts[-1][0], pts[-1][1]
    trend_last = math.exp(a * last_i + b)
    upper_last = math.exp(a * last_i + b + k * sigma)
    lower_last = math.exp(a * last_i + b - k * sigma)
    span = upper_last - lower_last
    position = (last_close - lower_last) / span if span else 0.5
    annualized = (math.exp(a * periods_per_year) - 1) * 100.0

    read = _read(position, annualized)
    caveat = ""
    if not reliable:
        caveat = (
            f"Residual autocorrelation is high ({autocorr:.2f}): the trend is "
            "non-linear over this window (a flat stretch then a sharp acceleration "
            "and reversal), so these bounds are descriptive geometry, not a 2.5% "
            "tail. Do not treat them as actionable levels — use the swing "
            "support/resistance below for that."
        )
    return TrendChannel(
        n=n, a=a, b=b, sigma=sigma, k=k, periods_per_year=periods_per_year,
        last_close=last_close, trend_last=trend_last, upper_last=upper_last,
        lower_last=lower_last, position=position, annualized_trend_pct=annualized,
        autocorr=autocorr, reliable=reliable, read=read, caveat=caveat,
    )


def _read(position: float, annualized: float) -> str:
    trend_dir = "rising" if annualized > 1 else "falling" if annualized < -1 else "flat"
    if position > 1.0:
        where = "above the channel — extended vs its long-run trend"
    elif position < 0.0:
        where = "below the channel — distended to the downside"
    elif position >= 0.66:
        where = "in the upper third of its long-run channel"
    elif position <= 0.34:
        where = "in the lower third of its long-run channel"
    else:
        where = "near the middle of its long-run channel"
    return f"Price is {where}; the secular trend is {trend_dir} (~{abs(annualized):.0f}%/yr)."


# --- Swing support / resistance ----------------------------------------------


@dataclass
class SwingLevels:
    highs: list = field(default_factory=list)   # [(date, price), ...] pivot highs
    lows: list = field(default_factory=list)    # [(date, price), ...] pivot lows
    all_time_high: tuple | None = None
    nearest_resistance: tuple | None = None     # lowest pivot high above price
    nearest_support: tuple | None = None        # highest pivot low below price


def swing_levels(bars: Sequence[PriceBar], left: int = 6, right: int = 6) -> SwingLevels:
    """Detect pivot highs/lows (a bar that is the extreme of its [-left,+right]
    neighbourhood) — the real levels where price turned."""
    series = [(b.date, b.close) for b in bars if b.close]
    n = len(series)
    highs, lows = [], []
    for idx in range(left, n - right):
        window = [c for _, c in series[idx - left: idx + right + 1]]
        d, c = series[idx]
        if c == max(window):
            highs.append((d, c))
        if c == min(window):
            lows.append((d, c))

    out = SwingLevels(highs=highs, lows=lows)
    if series:
        out.all_time_high = max(series, key=lambda t: t[1])
        last = series[-1][1]
        above = [h for h in highs if h[1] > last]
        below = [lo for lo in lows if lo[1] < last]
        if above:
            out.nearest_resistance = min(above, key=lambda t: t[1])
        if below:
            out.nearest_support = max(below, key=lambda t: t[1])
    return out
