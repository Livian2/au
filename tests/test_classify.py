"""Tests for indicator classification, especially the §4 decomposition rule."""

from datetime import date

from gold_regime_tracker.config import load_config
from gold_regime_tracker.classify import (
    classify_mm_net,
    classify_mm_short,
    classify_price,
    classify_cb,
    classify_etf,
)
from gold_regime_tracker.models import CotRecord, PriceBar, CbRecord, EtfRecord, State

CFG = load_config()
TODAY = date(2026, 6, 22)


def _cot(d, lng, sht, oi=500000):
    return CotRecord(d, d, lng, sht, lng - sht, 15000, oi)


def test_mm_net_healthy_baseline():
    s = classify_mm_net(CFG, _cot("2026-06-16", 126000, 20000), _cot("2026-06-09", 125000, 20000), TODAY)
    assert s.state == State.HEALTHY


def test_mm_net_decomposition_longs_liquidating_is_not_conviction():
    # Net falls 30k driven entirely by longs leaving; shorts flat.
    prior = _cot("2026-06-09", 90000, 20000)
    cur = _cot("2026-06-16", 60000, 20000)  # net 40k, below transition_min -> REGIME by level
    s = classify_mm_net(CFG, cur, prior, TODAY)
    assert "LONGS LIQUIDATING" in s.note
    assert "bottoming" in s.note.lower()


def test_mm_net_decomposition_shorts_initiating_is_conviction():
    prior = _cot("2026-06-09", 90000, 20000)
    cur = _cot("2026-06-16", 90000, 55000)  # net falls because shorts surged
    s = classify_mm_net(CFG, cur, prior, TODAY)
    assert "SHORTS INITIATING" in s.note


def test_mm_short_regime_requires_rising():
    prior = _cot("2026-06-09", 100000, 60000)
    cur = _cot("2026-06-16", 100000, 58000)  # elevated but FALLING
    s = classify_mm_short(CFG, cur, prior, TODAY)
    assert s.state == State.TRANSITION  # not REGIME, because not rising

    cur2 = _cot("2026-06-16", 100000, 62000)  # elevated and rising
    s2 = classify_mm_short(CFG, cur2, prior, TODAY)
    assert s2.state == State.REGIME


def test_mm_net_transition_requires_falling_oi():
    prior = _cot("2026-06-09", 100000, 20000, oi=500000)
    cur = _cot("2026-06-16", 80000, 20000, oi=500000)  # net 60k, OI not falling
    s = classify_mm_net(CFG, cur, prior, TODAY)
    assert s.state == State.HEALTHY

    cur2 = _cot("2026-06-16", 80000, 20000, oi=480000)  # OI falling
    s2 = classify_mm_net(CFG, cur2, prior, TODAY)
    assert s2.state == State.TRANSITION


def test_price_regime_below_support():
    s = classify_price(CFG, PriceBar(date="2026-06-19", close=4250.0), TODAY)
    assert s.state == State.REGIME


def test_price_healthy_above_support():
    s = classify_price(CFG, PriceBar(date="2026-06-19", close=4400.0), TODAY)
    assert s.state == State.HEALTHY


def test_cb_states():
    assert classify_cb(CFG, CbRecord(quarter="2026-Q1", qualitative="firm"), TODAY).state == State.HEALTHY
    assert classify_cb(CFG, CbRecord(quarter="2026-Q1", qualitative="softening"), TODAY).state == State.TRANSITION
    assert classify_cb(CFG, CbRecord(quarter="2026-Q1", qualitative="cooling"), TODAY).state == State.REGIME


def test_cb_staleness():
    # An ancient quarter must be flagged stale (excluded from counts).
    s = classify_cb(CFG, CbRecord(quarter="2024-Q1", qualitative="firm"), TODAY)
    assert s.stale is True


def test_etf_healthy():
    s = classify_etf(CFG, EtfRecord(month="2026-06", tonnes=4118.0, net_flow_usd=-3e8, ytd_flow_usd=12e9), [], TODAY)
    assert s.state == State.HEALTHY
