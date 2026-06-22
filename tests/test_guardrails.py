"""Tests for the §7 guardrails."""

from datetime import date, timedelta

from gold_regime_tracker.config import load_config
from gold_regime_tracker.guardrails import (
    min_interval_blocks,
    weekly_refresh_blocks,
    recommendation,
    reanchor_nag,
)
from gold_regime_tracker.models import Regime, RegimeAssessment, MacroGate

CFG = load_config()


def _hist(label, d):
    return {"date": d, "label": label.value, "confidence": 0.8, "macro_gate": "NEUTRAL", "firing_rows": []}


def test_min_interval_blocks_within_90_days():
    today = date(2026, 6, 22)
    history = [_hist(Regime.REGIME, "2026-05-01")]  # 52 days ago
    remaining = min_interval_blocks(CFG, history, today)
    assert remaining is not None and remaining > 0


def test_min_interval_clear_after_90_days():
    today = date(2026, 6, 22)
    history = [_hist(Regime.REGIME, "2026-01-01")]
    assert min_interval_blocks(CFG, history, today) is None


def test_weekly_cap_blocks_recompute():
    today = date(2026, 6, 22)
    history = [_hist(Regime.HEALTHY, "2026-06-19")]  # 3 days ago
    assert weekly_refresh_blocks(CFG, history, today) is not None


def test_weekly_cap_clears_after_7_days():
    today = date(2026, 6, 22)
    history = [_hist(Regime.HEALTHY, "2026-06-10")]
    assert weekly_refresh_blocks(CFG, history, today) is None


def test_act_eligible_suppressed_in_cooldown():
    today = date(2026, 6, 22)
    history = [_hist(Regime.REGIME, "2026-05-01")]
    a = RegimeAssessment(date=today.isoformat(), label=Regime.REGIME, macro_gate=MacroGate.HAWKISH)
    rec = recommendation(CFG, a, history, today, cb_stale=False)
    assert "SUPPRESSED" in rec


def test_healthy_recommendation_is_boring():
    today = date(2026, 6, 22)
    a = RegimeAssessment(date=today.isoformat(), label=Regime.HEALTHY)
    rec = recommendation(CFG, a, [], today, cb_stale=False)
    assert "No action" in rec


def test_stale_cb_adds_warning_on_regime():
    today = date(2026, 6, 22)
    a = RegimeAssessment(date=today.isoformat(), label=Regime.REGIME)
    recommendation(CFG, a, [], today, cb_stale=True)
    assert any("STALE CB_BID" in w for w in a.warnings)


def test_reanchor_nag_fires_when_old():
    # Baseline config is anchored 2026-06-22; a far-future "today" trips the nag.
    assert reanchor_nag(CFG, date(2027, 6, 22)) is not None
