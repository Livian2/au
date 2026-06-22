"""Assessment engine — wires the pieces together (spec §5 end-to-end).

Responsible for: building the current ``IndicatorState`` for each row from the
stored record series, computing each row's ``persisted_periods`` (so the §7.2
persistence filter has real history to act on), running the macro gate and state
machine, and applying the guardrail-aware recommendation.
"""

from __future__ import annotations

from datetime import date
from typing import Optional, Sequence

from . import classify, store
from .config import Config
from .guardrails import recommendation, weekly_refresh_blocks
from .models import IndicatorState, State
from .state_machine import classify_regime, evaluate_macro_gate


def _classify_cot_at(cfg: Config, series, idx: int, kind: str, today: date) -> IndicatorState:
    cur = series[idx]
    prior = series[idx - 1] if idx > 0 else None
    if kind == "MM_NET":
        return classify.classify_mm_net(cfg, cur, prior, today)
    return classify.classify_mm_short(cfg, cur, prior, today)


def _persisted_periods(states_back: Sequence[State]) -> int:
    """Count consecutive trailing periods sharing the most recent state."""
    if not states_back:
        return 1
    last = states_back[-1]
    count = 0
    for s in reversed(states_back):
        if s == last:
            count += 1
        else:
            break
    return count


def _cot_state(cfg: Config, kind: str, today: date) -> Optional[IndicatorState]:
    series = sorted(store.load_cot(), key=lambda r: r.report_date)
    if not series:
        return None
    idx = len(series) - 1
    current = _classify_cot_at(cfg, series, idx, kind, today)
    back = [
        _classify_cot_at(cfg, series, i, kind, today).state
        for i in range(max(0, idx - 5), idx + 1)
    ]
    current.persisted_periods = _persisted_periods(back)
    return current


def _price_state(cfg: Config, today: date) -> Optional[IndicatorState]:
    series = sorted(store.load_price(), key=lambda b: b.date)
    if not series:
        return None
    current = classify.classify_price(cfg, series[-1], today)
    back = [classify.classify_price(cfg, b, today).state for b in series[-6:]]
    current.persisted_periods = _persisted_periods(back)
    return current


def _etf_state(cfg: Config, today: date) -> Optional[IndicatorState]:
    series = sorted(store.load_etf(), key=lambda r: r.month)
    if not series:
        return None
    current = classify.classify_etf(cfg, series[-1], series[:-1], today)
    back = []
    for i in range(max(0, len(series) - 4), len(series)):
        back.append(classify.classify_etf(cfg, series[i], series[:i], today).state)
    current.persisted_periods = _persisted_periods(back)
    return current


def _cb_state(cfg: Config, today: date) -> Optional[IndicatorState]:
    series = sorted(store.load_cb(), key=lambda r: r.quarter)
    if not series:
        return None
    current = classify.classify_cb(cfg, series[-1], today)
    back = [classify.classify_cb(cfg, r, today).state for r in series[-4:]]
    current.persisted_periods = _persisted_periods(back)
    return current


def assess(cfg: Config, today: date, force: bool = False):
    """Run a full assessment. Returns (assessment, states, cb_stale, blocked).

    ``blocked`` is set when the §7.3 weekly cap would suppress the recompute and
    ``force`` is False — the caller should show the last assessment instead.
    """
    history = store.load_history()
    next_allowed = weekly_refresh_blocks(cfg, history, today)
    blocked = next_allowed if (next_allowed and not force) else None

    states: list[IndicatorState] = []
    for builder in (
        lambda: _cot_state(cfg, "MM_NET", today),
        lambda: _cot_state(cfg, "MM_SHORT", today),
        lambda: _etf_state(cfg, today),
        lambda: _price_state(cfg, today),
        lambda: _cb_state(cfg, today),
    ):
        s = builder()
        if s is not None:
            states.append(s)

    macro_series = sorted(store.load_macro(), key=lambda r: r.date)
    macro_cur = macro_series[-1] if macro_series else None
    macro_prior = macro_series[-2] if len(macro_series) > 1 else None
    if macro_cur is not None:
        gate = evaluate_macro_gate(cfg, macro_cur, macro_prior)
        macro_days, macro_stale = classify._staleness(cfg, "MACRO", macro_cur.date, today)
    else:
        from .models import MacroGate

        gate = MacroGate.NEUTRAL
        macro_stale = True

    assessment = classify_regime(cfg, states, gate, macro_stale)
    assessment.date = today.isoformat()

    cb_state = next((s for s in states if s.id == "CB_BID"), None)
    cb_stale = cb_state is None or cb_state.stale
    assessment.recommendation = recommendation(cfg, assessment, history, today, cb_stale)

    return assessment, states, cb_stale, blocked
