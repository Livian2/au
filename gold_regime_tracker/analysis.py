"""Price-structure analysis — the upper/lower bounds shown on the chart.

Method: a least-squares **linear regression channel** over the lookback window.
The centre line is the regression trend; the upper and lower bounds are the trend
shifted by ``k`` standard deviations of the residuals (default 2σ). This is a
standard, transparent way to bound a trending series — wide enough that touches
are meaningful, narrow enough to be informative. It is descriptive structure, not
a forecast (consistent with the spec: this tool confirms, it does not predict).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

from .models import PriceBar


@dataclass
class ChannelAnalysis:
    n: int
    slope: float            # price change per period (period = spacing of bars)
    intercept: float
    sigma: float            # std dev of residuals about the trend
    k: float                # number of sigmas for the bounds
    periods_per_year: float
    trend_last: float
    upper_last: float
    lower_last: float
    position: float         # where last close sits in [lower=0, upper=1]
    annualized_trend_pct: float
    read: str

    def trend_at(self, i: float) -> float:
        return self.slope * i + self.intercept

    def upper_at(self, i: float) -> float:
        return self.trend_at(i) + self.k * self.sigma

    def lower_at(self, i: float) -> float:
        return self.trend_at(i) - self.k * self.sigma


def linear_channel(
    bars: Sequence[PriceBar], k: float = 2.0, periods_per_year: float = 52.0
) -> ChannelAnalysis | None:
    """Fit price = slope*i + intercept by least squares; bound by k residual σ."""
    pts = [(i, b.close) for i, b in enumerate(bars) if b.close is not None]
    n = len(pts)
    if n < 8:
        return None

    sx = sum(i for i, _ in pts)
    sy = sum(y for _, y in pts)
    sxx = sum(i * i for i, _ in pts)
    sxy = sum(i * y for i, y in pts)
    denom = n * sxx - sx * sx
    if denom == 0:
        return None
    slope = (n * sxy - sx * sy) / denom
    intercept = (sy - slope * sx) / n

    residuals = [y - (slope * i + intercept) for i, y in pts]
    sigma = math.sqrt(sum(r * r for r in residuals) / n)

    last_i = pts[-1][0]
    last_close = pts[-1][1]
    trend_last = slope * last_i + intercept
    upper_last = trend_last + k * sigma
    lower_last = trend_last - k * sigma
    span = upper_last - lower_last
    position = (last_close - lower_last) / span if span else 0.5

    annualized = (slope * periods_per_year / last_close * 100.0) if last_close else 0.0
    read = _read(position, annualized)

    return ChannelAnalysis(
        n=n,
        slope=slope,
        intercept=intercept,
        sigma=sigma,
        k=k,
        periods_per_year=periods_per_year,
        trend_last=trend_last,
        upper_last=upper_last,
        lower_last=lower_last,
        position=position,
        annualized_trend_pct=annualized,
        read=read,
    )


def _read(position: float, annualized: float) -> str:
    trend_dir = "rising" if annualized > 1 else "falling" if annualized < -1 else "flat"
    if position > 1.0:
        where = "stretched ABOVE the channel's upper bound — extended vs its trend"
    elif position < 0.0:
        where = "below the channel's lower bound — distended to the downside"
    elif position >= 0.66:
        where = "in the upper third of its regression channel"
    elif position <= 0.34:
        where = "in the lower third of its regression channel"
    else:
        where = "near the middle of its regression channel"
    return f"Price is {where}; the {abs(annualized):.0f}%/yr trend is {trend_dir}."
