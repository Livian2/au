"""Baseline example data — illustrative, NOT live.

The price path is a *stylised reconstruction* of the real gold trajectory over
the window (flat 2023–24 near \\$1,950, convex acceleration through 2025 to the
Dec-2025 high ~\\$4,530, the late-Jan-2026 blow-off to an all-time ~\\$5,414 and
the single-day crash, then the H1-2026 pullback to ~\\$4,144). It is marked
``source="synthetic"`` so the dashboard stamps it as illustrative. Replace it
with real history via ``fetch price --file`` and the chart/analysis recompute.

The voting rows are set to a coherent *pullback* board: price has broken its
shelf and the macro gate is hawkish, but the central-bank floor still holds — so
the tool reads TRANSITION / WATCH (a pullback while the floor holds is, by the
spec's own rule, not yet a confirmed regime change).
"""

from __future__ import annotations

import random
from datetime import date, timedelta

from . import store
from .models import CbRecord, CotRecord, EtfRecord, MacroRecord, PriceBar

# (date, weekly close) waypoints of the stylised real path; weeks between are
# interpolated. The spike/crash weeks are pinned so they are NOT smoothed away.
_WAYPOINTS = [
    ("2023-06-23", 1925),
    ("2023-12-29", 2060),
    ("2024-06-28", 2180),   # ~flat through 2024
    ("2024-12-27", 2330),
    ("2025-06-27", 3060),   # convex acceleration begins
    ("2025-09-26", 3760),
    ("2025-12-26", 4530),   # Dec-2025 high (~4,533)
    ("2026-01-23", 5060),   # run-up
    ("2026-01-30", 5414),   # all-time-high blow-off
    ("2026-02-06", 4920),   # ~-500 single-week crash
    ("2026-03-27", 4760),
    ("2026-04-24", 4610),
    ("2026-05-22", 4515),
    ("2026-06-05", 4360),   # rolling over
    ("2026-06-12", 4250),   # third consecutive weekly decline begins to bite
    ("2026-06-19", 4144),   # current print (~-8% MoM)
]


def _interpolate_weekly() -> list[tuple[str, float]]:
    rng = random.Random(20260622)
    wp = [(date.fromisoformat(d), float(p)) for d, p in _WAYPOINTS]
    out: list[tuple[str, float]] = []
    for (d0, p0), (d1, p1) in zip(wp, wp[1:]):
        weeks = max(1, round((d1 - d0).days / 7))
        for w in range(weeks):
            f = w / weeks
            price = p0 + (p1 - p0) * f
            # Light noise, suppressed near the pinned spike/crash so they stay sharp.
            noise = rng.gauss(0, 22) if abs(price - 5414) > 200 else 0
            out.append(((d0 + timedelta(weeks=w)).isoformat(), round(price + noise, 1)))
    out.append((wp[-1][0].isoformat(), wp[-1][1]))  # pin the final print exactly
    return out


def _synthetic_price_history() -> list[PriceBar]:
    rows = _interpolate_weekly()
    closes = [p for _, p in rows]
    bars, window = [], 40  # ~200 trading days
    for i, (d, close) in enumerate(rows):
        ma = round(sum(closes[max(0, i - window + 1): i + 1]) / min(i + 1, window), 1)
        bars.append(
            PriceBar(
                date=d,
                close=close,
                sma200=ma,
                dist_200dma_pct=round((close - ma) / ma * 100, 2),
                source="synthetic",
            )
        )
    return bars


def _cot(d, long_, short_, oi):
    return CotRecord(d, d, long_, short_, long_ - short_, 15000, oi)


def seed_baseline() -> int:
    count = 0

    for bar in _synthetic_price_history():
        store.save_price(bar)
        count += 1

    # COT — managed money softening: net bleeding into the 50–70k transition band
    # on falling open interest; gross short creeping into 35–55k (TRANSITION).
    for d, lng, sht, oi in [
        ("2026-05-26", 95000, 34000, 470000),
        ("2026-06-02", 94000, 36000, 462000),
        ("2026-06-09", 93000, 37000, 455000),
        ("2026-06-16", 92000, 38000, 448000),
    ]:
        store.save_cot(_cot(d, lng, sht, oi))
        count += 1

    # ETF — holdings slipping into the 3,900–4,000 band on consecutive monthly
    # outflows (TRANSITION); Western flows leaving.
    for m, tonnes, net, ytd in [
        ("2026-03", 4080.0, -1.0e9, 8.0e9),
        ("2026-04", 4020.0, -1.5e9, 5.0e9),
        ("2026-05", 3980.0, -2.0e9, 2.0e9),
        ("2026-06", 3960.0, -1.2e9, -0.5e9),
    ]:
        store.save_etf(EtfRecord(month=m, tonnes=tonnes, net_flow_usd=net, ytd_flow_usd=ytd))
        count += 1

    # Central-bank bid — still firm. The price-inelastic structural floor holds,
    # which is what keeps this a pullback rather than a confirmed regime change.
    for q, qual, otc in [("2025-Q4", "firm", 340.0), ("2026-Q1", "firm", 315.0)]:
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

    # Macro — hawkish gate: dollar at a 1-yr high, a more hawkish Fed (≈9 of 19
    # expecting at least one more hike), hike odds rising, oil/Hormuz firm.
    for d, odds in [("2026-06-08", 88.0), ("2026-06-15", 91.0)]:
        store.save_macro(
            MacroRecord(
                date=d,
                hike_odds_pct=odds,
                last_cpi_surprise_bp=15.0,
                brent_close=78.0,
                brent_direction="rising",
                hormuz_state="tense",
                note="Stronger USD (1-yr high), hawkish Fed dots, hike odds rising.",
            )
        )
        count += 1

    # Record source metadata so the dashboard's data-sources panel is populated.
    # fetched_at is set to each feed's latest observation (deterministic demo).
    for feed, source, fetched in [
        ("cot", "CFTC Disaggregated COT (synthetic demo)", "2026-06-16"),
        ("price", "Stooq XAU/USD (synthetic demo)", "2026-06-19"),
        ("etf", "WGC Goldhub (synthetic demo)", "2026-06-01"),
        ("cb", "Manual journal (synthetic demo)", "2026-04-30"),
        ("macro", "CME FedWatch (synthetic demo)", "2026-06-15"),
    ]:
        store.record_source(feed, source, fetched, detail="illustrative baseline")

    return count
