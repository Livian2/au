"""Guardrails (spec §7) — build these first; they are load-bearing.

1. Minimum decision interval: refuse a second act-eligible recommendation
   within 90 days of the last one, regardless of data.
2. No single-print actions: enforced in the state machine via the persistence
   filter; re-checked here defensively.
3. Weekly cap on dashboard refresh.
4. Stale-data honesty: confidence is reduced (handled in state_machine), and a
   stale high-weight manual row turns a clean verdict into a warning.
5. Event-risk disclaimer (rendered in output).
6. Anti-anchoring: nag when thresholds are > ~6 months old.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional

from .config import Config
from .models import IndicatorState, Regime, RegimeAssessment


def _parse(d: str) -> date:
    return datetime.strptime(d, "%Y-%m-%d").date()


def last_act_eligible_date(history: list[dict]) -> Optional[date]:
    """Most recent assessment that surfaced an act-eligible (REGIME) verdict."""
    acts = [
        _parse(h["date"])
        for h in history
        if h.get("label") == Regime.REGIME.value and h.get("date")
    ]
    return max(acts) if acts else None


def min_interval_blocks(cfg: Config, history: list[dict], today: date) -> Optional[int]:
    """Return days remaining in the 90-day cooldown, or None if clear (§7.1)."""
    last = last_act_eligible_date(history)
    if last is None:
        return None
    interval = int(cfg["guardrails"]["min_decision_interval_days"])
    elapsed = (today - last).days
    if elapsed < interval:
        return interval - elapsed
    return None


def weekly_refresh_blocks(cfg: Config, history: list[dict], today: date) -> Optional[date]:
    """If the assessment already ran within the past 7 days, return the date of
    the next allowed recompute, else None (§7.3)."""
    if not cfg["guardrails"].get("weekly_refresh", True):
        return None
    if not history:
        return None
    last_run = max(_parse(h["date"]) for h in history if h.get("date"))
    if (today - last_run).days < 7:
        return last_run + timedelta(days=7)
    return None


def recommendation(
    cfg: Config,
    assessment: RegimeAssessment,
    history: list[dict],
    today: date,
    cb_stale: bool,
) -> str:
    """Holder-calibrated, deliberately boring recommendation text (§6) with the
    §7.1 minimum-interval gate applied to act-eligible verdicts."""
    label = assessment.label

    if label == Regime.HEALTHY:
        nxt = (today + timedelta(days=7)).isoformat()
        return f"No action. Next scheduled review: {nxt}."

    if label == Regime.TRANSITION:
        return "Review only. Do not transact. Re-check after next CB_BID print."

    # REGIME — act-eligible, but gated.
    if cb_stale:
        assessment.warnings.append(
            "Regime label computed with a STALE CB_BID row — this is a warning, "
            "not a clean verdict (§6). Refresh the central-bank journal before "
            "treating this as actionable."
        )
    remaining = min_interval_blocks(cfg, history, today)
    if remaining is not None:
        return (
            f"Act-eligible signal SUPPRESSED: {remaining} days remain in the "
            f"{cfg['guardrails']['min_decision_interval_days']}-day minimum decision "
            "interval since the last act-eligible verdict (§7.1). Hold."
        )
    return (
        "Eligible for a deliberate review of core sizing — subject to the §7 "
        "minimum interval. This is not an instruction to transact."
    )


def reanchor_nag(cfg: Config, today: date) -> Optional[str]:
    """§7.6 anti-anchoring."""
    if cfg.reanchor_overdue(today):
        age = (today - cfg.last_reanchored).days
        return (
            f"Thresholds were last re-anchored {age} days ago "
            f"({cfg.last_reanchored.isoformat()}). Re-baseline against current "
            "levels rather than stale ones (§7.6)."
        )
    return None


EVENT_RISK_DISCLAIMER = (
    "This tracker is silent between weekly snapshots and cannot price a gap move "
    "on a Hormuz / CPI / Fed headline. It is for trend confirmation, not event "
    "protection (§7.5)."
)
