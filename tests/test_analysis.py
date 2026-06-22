"""Tests for the regression-channel bounds analysis."""

from gold_regime_tracker.analysis import linear_channel
from gold_regime_tracker.models import PriceBar


def _bars(closes):
    return [PriceBar(date=f"2026-01-{i+1:02d}", close=c) for i, c in enumerate(closes)]


def test_too_short_returns_none():
    assert linear_channel(_bars([1, 2, 3])) is None


def test_recovers_known_slope_and_zero_sigma_on_a_line():
    # Perfect line: close = 100 + 10*i  -> slope 10, residuals ~0.
    ch = linear_channel(_bars([100 + 10 * i for i in range(20)]), k=2.0, periods_per_year=52)
    assert ch is not None
    assert abs(ch.slope - 10) < 1e-6
    assert ch.sigma < 1e-6
    # On a perfect line the last point sits on the trend => mid-channel.
    assert abs(ch.trend_last - ch.upper_last) < 1e-6  # band collapses (sigma 0)


def test_bounds_ordered_and_position_in_range():
    closes = [100, 104, 103, 108, 110, 109, 115, 118, 117, 122, 121, 126]
    ch = linear_channel(_bars(closes), k=2.0)
    assert ch is not None
    assert ch.lower_last < ch.trend_last < ch.upper_last
    assert 0.0 <= ch.position <= 1.0


def test_annualized_trend_sign():
    up = linear_channel(_bars([100 + 5 * i for i in range(30)]))
    down = linear_channel(_bars([300 - 5 * i for i in range(30)]))
    assert up.annualized_trend_pct > 0
    assert down.annualized_trend_pct < 0
