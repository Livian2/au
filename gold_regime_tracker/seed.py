"""Baseline example data (spec §2 reference prints, ~June 22, 2026).

Loading this lets you run `assess` immediately and see a realistic HEALTHY
CONSOLIDATION board before wiring up the live fetchers. Numbers mirror the
reference levels quoted in the spec; they are illustrative, not live.
"""

from __future__ import annotations

from . import store
from .models import CbRecord, CotRecord, EtfRecord, MacroRecord, PriceBar


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

    # Price — weekly closes above the 4300 support shelf (HEALTHY).
    for d, close, sma200 in [
        ("2026-05-29", 4395.0, 4330.0),
        ("2026-06-05", 4410.0, 4335.0),
        ("2026-06-12", 4388.0, 4338.0),
        ("2026-06-19", 4402.0, 4340.0),
    ]:
        dist = round((close - sma200) / sma200 * 100, 2)
        store.save_price(PriceBar(date=d, close=close, sma200=sma200, dist_200dma_pct=dist))
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
