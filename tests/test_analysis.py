"""Tests for the trend channel and swing support/resistance."""

import math

from gold_regime_tracker.analysis import trend_channel, swing_levels
from gold_regime_tracker.models import PriceBar


def _bars(closes):
    return [PriceBar(date=f"2026-01-{i+1:02d}", close=c) for i, c in enumerate(closes)]


def test_too_short_returns_none():
    assert trend_channel(_bars([1, 2, 3])) is None


def test_clean_exponential_is_reliable_with_ordered_bounds():
    # A clean exponential is linear in log space => tiny residuals, reliable.
    closes = [1000 * math.exp(0.02 * i) for i in range(40)]
    ch = trend_channel(_bars(closes), k=2.0)
    assert ch is not None
    assert ch.reliable is True
    assert ch.lower_last < ch.trend_last < ch.upper_last
    assert ch.annualized_trend_pct > 0


def test_bent_series_is_flagged_unreliable():
    # Flat, then a sharp ramp and reversal => serially-correlated residuals.
    flat = [2000 + (i % 2) for i in range(30)]
    ramp = [2000 + 200 * (i + 1) for i in range(10)]
    crash = [4000 - 150 * (i + 1) for i in range(6)]
    ch = trend_channel(_bars(flat + ramp + crash), k=2.0)
    assert ch is not None
    assert ch.reliable is False
    assert ch.caveat  # carries the "not a 2.5% tail" warning


def test_swing_levels_finds_pivots_and_neighbours():
    # A clear peak at 150 and a clear trough at 50, ending near 100.
    closes = (
        [100, 110, 120, 135, 150, 140, 125, 110, 95, 70, 55, 50, 60, 80, 95, 100]
    )
    sw = swing_levels(_bars(closes), left=3, right=3)
    assert sw.all_time_high[1] == 150
    # nearest resistance is a pivot high above the last close (100)
    assert sw.nearest_resistance is None or sw.nearest_resistance[1] > 100
    # nearest support is a pivot low below the last close
    assert sw.nearest_support is None or sw.nearest_support[1] < 100
