"""Baseline example data (spec §2 reference prints, ~June 22, 2026).

Loading this lets you run `assess` immediately and see a realistic HEALTHY
CONSOLIDATION board before wiring up the live fetchers. Numbers mirror the
reference levels quoted in the spec; they are illustrative, not live.
"""

from __future__ import annotations

import math
import random
from datetime import date, timedelta

from . import store
from .models import CbRecord, CotRecord, EtfRecord, MacroRecord, PriceBar


def _synthetic_price_history(weeks: int = 157, end: date = date(2026, 6, 19)) -> list[PriceBar]:
    """Deterministic ~3-year weekly close series climbing ~2400 -> ~4400 with
    cyclical swings and noise. Illustrative only — replace with real data via
    `fetch price`. The last close is pinned to 4402 to match the spec baseline.
    """
    rng = random.Random(20260622)
    start_price, end_price = 2400.0, 4350.0
    closes: list[float] = []
    for w in range(weeks):
        f = w / (weeks - 1)
        trend = start_price + (end_price - start_price) * f
        cycle = 140.0 * math.sin(f * math.pi * 3.2)          # multi-month swings
        drift = rng.gauss(0, 28.0)                            # week-to-week noise
        closes.append(round(trend + cycle + drift, 1))
    closes[-1] = 4402.0  # pin the latest weekly close to the baseline print

    bars: list[PriceBar] = []
    window = 40  # ~200 trading days for the moving-average proxy
    for i, close in enumerate(closes):
        d = end - timedelta(weeks=(weeks - 1 - i))
        ma = round(sum(closes[max(0, i - window + 1): i + 1]) / min(i + 1, window), 1)
        dist = round((close - ma) / ma * 100, 2)
        bars.append(PriceBar(date=d.isoformat(), close=close, sma200=ma, dist_200dma_pct=dist))
    return bars


def _cot(report_date: str, long_: int, short_: int, oi: int) -> CotRecord:
    return CotRecord(
        report_date=report_date,
        fetch_date=report_date,
        mm_long=long_,
        mm_short=short_,
        mm_net=long_ - short_,
        mm_spread=15000,
        open_interest=oi,
    )


def seed_baseline() -> int:
    count = 0

    # CFTC COT — managed money near baseline (net ~106k, gross short ~20k => HEALTHY).
    for d, lng, sht, oi in [
        ("2026-05-26", 127000, 21000, 505000),
        ("2026-06-02", 126500, 20500, 503000),
        ("2026-06-09", 126000, 20000, 502000),
        ("2026-06-16", 126200, 20300, 501000),
    ]:
        store.save_cot(_cot(d, lng, sht, oi))
        count += 1

    # Price — ~3 years of weekly closes, deterministic, ending ~4402 above the
    # 4300 support shelf (HEALTHY). Gives the dashboard chart its history.
    for bar in _synthetic_price_history():
        store.save_price(bar)
        count += 1

    # ETF — holdings above 4000t with positive YTD flow (HEALTHY); May first outflow.
    for m, tonnes, net, ytd in [
        ("2026-03", 4150.0, 1.2e9, 14.0e9),
        ("2026-04", 4135.0, 0.5e9, 14.5e9),
        ("2026-05", 4121.0, -2.0e9, 12.5e9),
        ("2026-06", 4118.0, -0.3e9, 12.2e9),
    ]:
        store.save_etf(EtfRecord(month=m, tonnes=tonnes, net_flow_usd=net, ytd_flow_usd=ytd))
        count += 1

    # Central-bank bid — firm (HEALTHY); the price-inelastic structural floor.
    for q, qual, otc in [("2025-Q4", "firm", 330.0), ("2026-Q1", "firm", 310.0)]:
        store.save_cb(
            CbRecord(
                quarter=q,
                qualitative=qual,
                otc_adjusted_t=otc,
                note="WGC OTC-adjusted estimate; official trade data under-captures sovereign buying.",
                entered_by="Ole",
                entered_on="2026-04-30",
            )
        )
        count += 1

    # Macro — ~87% Dec hike implied, flat/steady => NEUTRAL gate.
    for d, odds in [("2026-06-08", 87.0), ("2026-06-15", 87.0)]:
        store.save_macro(
            MacroRecord(
                date=d,
                hike_odds_pct=odds,
                last_cpi_surprise_bp=2.0,
                brent_close=72.0,
                brent_direction="flat",
                hormuz_state="calm",
                note="Baseline: hike odds steady, oil rangebound, Hormuz calm.",
            )
        )
        count += 1

    return count
