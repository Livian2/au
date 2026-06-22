"""Indicator classification (spec §4).

Each voting row is classified independently into HEALTHY / TRANSITION / REGIME
using the thresholds in config. The most important piece of intelligence here is
the **decomposition rule** (§4): a falling ``MM_NET`` is ambiguous — it can mean
longs liquidating (passive exhaustion, often a bottoming tell) or shorts
initiating (active down-conviction). Those look identical in the net number and
mean opposite things, so we always evaluate ``MM_SHORT`` alongside ``MM_NET``
and surface the decomposition.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional, Sequence

from .config import Config
from .models import (
    CbRecord,
    CotRecord,
    EtfRecord,
    IndicatorState,
    PriceBar,
    State,
)


def _days_between(as_of: str, today: date) -> int:
    d = datetime.strptime(as_of, "%Y-%m-%d").date()
    return (today - d).days


def _staleness(cfg: Config, indicator_id: str, as_of: str, today: date) -> tuple[int, bool]:
    days = _days_between(as_of, today)
    limit = cfg.cadence_days(indicator_id) * cfg.staleness_multiplier
    return days, days > limit


# --- MM_NET + MM_SHORT --------------------------------------------------------


def classify_mm_net(
    cfg: Config, current: CotRecord, prior: Optional[CotRecord], today: date
) -> IndicatorState:
    t = cfg["MM_NET"]
    net = current.mm_net
    oi_falling = prior is not None and current.open_interest < prior.open_interest

    if net >= t["healthy_min"]:
        state, hit = State.HEALTHY, f"mm_net {net} >= {t['healthy_min']}"
    elif net >= t["transition_min"]:
        # Transition requires the "with falling open_interest" qualifier (§4).
        if oi_falling:
            state, hit = State.TRANSITION, f"mm_net {net} in [{t['transition_min']},{t['healthy_min']}) + OI falling"
        else:
            state, hit = State.HEALTHY, f"mm_net {net} soft but OI not falling — not yet transition"
    else:
        state, hit = State.REGIME, f"mm_net {net} < {t['transition_min']} toward flat/negative"

    days, stale = _staleness(cfg, "MM_NET", current.report_date, today)
    note = _decomposition_note(current, prior)
    return IndicatorState(
        id="MM_NET",
        state=state,
        value=f"net={net} (long={current.mm_long}, short={current.mm_short})",
        threshold_hit=hit,
        as_of=current.report_date,
        staleness_days=days,
        stale=stale,
        note=note,
    )


def _decomposition_note(current: CotRecord, prior: Optional[CotRecord]) -> str:
    """The §4 decomposition: is a falling net longs leaving or shorts arriving?"""
    if prior is None:
        return "No prior COT to decompose net change."
    d_net = current.mm_net - prior.mm_net
    d_long = current.mm_long - prior.mm_long
    d_short = current.mm_short - prior.mm_short
    if d_net >= 0:
        return f"Net rising (+{d_net}); longs {d_long:+}, shorts {d_short:+}."
    # Net is falling — which leg drove it?
    if abs(d_short) > abs(d_long) and d_short > 0:
        driver = ("SHORTS INITIATING — active down-conviction (the meaningful tell). "
                  "Weight this toward REGIME.")
    elif d_long < 0 and abs(d_long) >= abs(d_short):
        driver = ("LONGS LIQUIDATING — passive exhaustion, often a bottoming tell, "
                  "NOT a conviction signal. Do not read as regime change.")
    else:
        driver = "Mixed: both legs moving; read MM_SHORT directly."
    return f"Net falling ({d_net}); longs {d_long:+}, shorts {d_short:+}. {driver}"


def classify_mm_short(
    cfg: Config, current: CotRecord, prior: Optional[CotRecord], today: date
) -> IndicatorState:
    t = cfg["MM_SHORT"]
    short = current.mm_short
    rising = prior is not None and current.mm_short > prior.mm_short

    if short < t["healthy_max"]:
        state, hit = State.HEALTHY, f"gross short {short} < {t['healthy_max']}"
    elif short <= t["transition_max"]:
        state, hit = State.TRANSITION, f"gross short {short} in [{t['healthy_max']},{t['transition_max']}]"
    else:
        # Regime requires "and rising" — funds actively short, not just elevated.
        if rising:
            state, hit = State.REGIME, f"gross short {short} > {t['transition_max']} and rising"
        else:
            state, hit = State.TRANSITION, f"gross short {short} elevated but not rising"

    days, stale = _staleness(cfg, "MM_SHORT", current.report_date, today)
    return IndicatorState(
        id="MM_SHORT",
        state=state,
        value=f"gross_short={short}" + (" (rising)" if rising else ""),
        threshold_hit=hit,
        as_of=current.report_date,
        staleness_days=days,
        stale=stale,
        note="Best conviction tell: rising gross shorts is the only conviction signal in the COT data.",
    )


# --- ETF_HOLD -----------------------------------------------------------------


def classify_etf(
    cfg: Config, current: EtfRecord, history: Sequence[EtfRecord], today: date
) -> IndicatorState:
    t = cfg["ETF_HOLD"]
    tonnes = current.tonnes
    consec_out = _consecutive_outflows(history, current)

    if tonnes >= t["healthy_tonnes_min"] and (current.ytd_flow_usd or 0) > 0:
        state, hit = State.HEALTHY, f"tonnes {tonnes} >= {t['healthy_tonnes_min']} and ytd_flow > 0"
    elif (
        t["transition_tonnes_min"] <= tonnes < t["healthy_tonnes_min"]
        and consec_out >= t["transition_consecutive_outflows"]
    ):
        state, hit = State.TRANSITION, f"tonnes {tonnes} in band + {consec_out} consecutive outflows"
    elif tonnes < t["transition_tonnes_min"] and (current.ytd_flow_usd or 0) < 0:
        accel = _accelerating_outflows(history, current)
        state = State.REGIME
        hit = f"tonnes {tonnes} < {t['transition_tonnes_min']}, ytd_flow < 0" + (", accelerating" if accel else "")
    else:
        # Ambiguous middle — default to the milder classification.
        state = State.TRANSITION if consec_out >= 1 else State.HEALTHY
        hit = f"tonnes {tonnes}, {consec_out} recent outflow(s)"

    month_as_date = current.month + "-01"
    days, stale = _staleness(cfg, "ETF_HOLD", month_as_date, today)
    return IndicatorState(
        id="ETF_HOLD",
        state=state,
        value=f"{tonnes}t, ytd_flow={current.ytd_flow_usd}",
        threshold_hit=hit,
        as_of=current.month,
        staleness_days=days,
        stale=stale,
    )


def _consecutive_outflows(history: Sequence[EtfRecord], current: EtfRecord) -> int:
    series = list(history) + [current]
    series.sort(key=lambda r: r.month)
    count = 0
    for rec in reversed(series):
        if (rec.net_flow_usd or 0) < 0:
            count += 1
        else:
            break
    return count


def _accelerating_outflows(history: Sequence[EtfRecord], current: EtfRecord) -> bool:
    series = sorted(list(history) + [current], key=lambda r: r.month)
    outs = [r.net_flow_usd for r in series[-3:] if r.net_flow_usd is not None]
    return len(outs) >= 2 and outs[-1] < outs[-2] < 0


# --- PRICE --------------------------------------------------------------------


def classify_price(cfg: Config, bar: PriceBar, today: date) -> IndicatorState:
    t = cfg["PRICE"]
    close = bar.close
    if close > t["healthy_close_min"]:
        state, hit = State.HEALTHY, f"weekly close {close} > {t['healthy_close_min']}"
    elif close <= t["transition_close_max"] and close > t["healthy_close_min"] - 0.0001:
        state, hit = State.TRANSITION, "in choppy/capped band"
    elif close < t["healthy_close_min"]:
        state, hit = State.REGIME, f"decisive close {close} < {t['healthy_close_min']} (opens {cfg['reference_levels']['next_support']})"
    else:
        state, hit = State.TRANSITION, "choppy/capped band"

    days, stale = _staleness(cfg, "PRICE", bar.date, today)
    dist = f", {bar.dist_200dma_pct:+.1f}% vs 200DMA" if bar.dist_200dma_pct is not None else ""
    return IndicatorState(
        id="PRICE",
        state=state,
        value=f"close={close}{dist}",
        threshold_hit=hit,
        as_of=bar.date,
        staleness_days=days,
        stale=stale,
    )


# --- CB_BID (manual) ----------------------------------------------------------


def classify_cb(cfg: Config, rec: CbRecord, today: date) -> IndicatorState:
    t = cfg["CB_BID"]
    q = (rec.qualitative or "").strip().lower()
    if q in t["healthy_states"]:
        state = State.HEALTHY
    elif q in t["transition_states"]:
        state = State.TRANSITION
    elif q in t["regime_states"]:
        state = State.REGIME
    else:
        state = State.HEALTHY  # unknown => do not manufacture alarm

    as_of = _quarter_to_date(rec.quarter)
    days, stale = _staleness(cfg, "CB_BID", as_of, today)
    return IndicatorState(
        id="CB_BID",
        state=state,
        value=f"{q or 'unknown'} (otc_adjusted={rec.otc_adjusted_t})",
        threshold_hit=f"qualitative read: {q or 'unknown'}",
        as_of=as_of,
        staleness_days=days,
        stale=stale,
        note=rec.note,
    )


def _quarter_to_date(quarter: str) -> str:
    """Map e.g. '2026-Q1' to the date that quarter's data describes (quarter end)."""
    try:
        year, q = quarter.split("-Q")
        end_month = {"1": "03-31", "2": "06-30", "3": "09-30", "4": "12-31"}[q.strip()]
        return f"{year}-{end_month}"
    except Exception:
        return quarter
