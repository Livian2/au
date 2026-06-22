"""Tests for the regime state machine, especially the §5 non-negotiable rule."""

from gold_regime_tracker.config import load_config
from gold_regime_tracker.models import IndicatorState, MacroGate, Regime, State
from gold_regime_tracker.state_machine import classify_regime

CFG = load_config()


def _row(id_, state, persisted=2, stale=False):
    return IndicatorState(
        id=id_,
        state=state,
        value="",
        threshold_hit="",
        as_of="2026-06-16",
        staleness_days=1,
        stale=stale,
        persisted_periods=persisted,
    )


def test_all_healthy_is_consolidation():
    rows = [_row(i, State.HEALTHY) for i in ("MM_NET", "MM_SHORT", "ETF_HOLD", "PRICE", "CB_BID")]
    a = classify_regime(CFG, rows, MacroGate.NEUTRAL)
    assert a.label == Regime.HEALTHY


def test_three_transition_is_watch():
    rows = [
        _row("MM_NET", State.TRANSITION),
        _row("MM_SHORT", State.TRANSITION),
        _row("PRICE", State.TRANSITION),
        _row("ETF_HOLD", State.HEALTHY),
        _row("CB_BID", State.HEALTHY),
    ]
    a = classify_regime(CFG, rows, MacroGate.NEUTRAL)
    assert a.label == Regime.TRANSITION


def test_flows_alone_cannot_declare_regime():
    # Three flow rows in REGIME, but CB_BID holds and macro is neutral.
    rows = [
        _row("MM_NET", State.REGIME),
        _row("MM_SHORT", State.REGIME),
        _row("PRICE", State.REGIME),
        _row("ETF_HOLD", State.REGIME),
        _row("CB_BID", State.HEALTHY),
    ]
    a = classify_regime(CFG, rows, MacroGate.NEUTRAL)
    assert a.label == Regime.TRANSITION  # held down by the non-negotiable rule
    assert any("non-negotiable" in w for w in a.warnings)


def test_regime_with_cb_failing():
    rows = [
        _row("MM_NET", State.REGIME),
        _row("MM_SHORT", State.REGIME),
        _row("PRICE", State.REGIME),
        _row("ETF_HOLD", State.HEALTHY),
        _row("CB_BID", State.REGIME),
    ]
    a = classify_regime(CFG, rows, MacroGate.NEUTRAL)
    assert a.label == Regime.REGIME


def test_regime_with_hawkish_macro_gate():
    rows = [
        _row("MM_NET", State.REGIME),
        _row("MM_SHORT", State.REGIME),
        _row("PRICE", State.REGIME),
        _row("ETF_HOLD", State.HEALTHY),
        _row("CB_BID", State.HEALTHY),
    ]
    a = classify_regime(CFG, rows, MacroGate.HAWKISH)
    assert a.label == Regime.REGIME


def test_persistence_filter_blocks_single_print():
    # REGIME rows that have NOT persisted 2 periods must not count.
    rows = [
        _row("MM_NET", State.REGIME, persisted=1),
        _row("MM_SHORT", State.REGIME, persisted=1),
        _row("PRICE", State.REGIME, persisted=1),
        _row("ETF_HOLD", State.HEALTHY),
        _row("CB_BID", State.REGIME, persisted=1),
    ]
    a = classify_regime(CFG, rows, MacroGate.HAWKISH)
    assert a.label == Regime.HEALTHY


def test_stale_cb_reduces_confidence():
    rows = [
        _row("MM_NET", State.HEALTHY),
        _row("MM_SHORT", State.HEALTHY),
        _row("PRICE", State.HEALTHY),
        _row("ETF_HOLD", State.HEALTHY),
        _row("CB_BID", State.HEALTHY, stale=True),  # excluded from fresh set
    ]
    a = classify_regime(CFG, rows, MacroGate.NEUTRAL)
    # CB excluded => confidence penalised below 1.0
    assert a.confidence < 1.0


def test_dovish_gate_fades_flow_break():
    rows = [
        _row("MM_NET", State.REGIME),
        _row("MM_SHORT", State.REGIME),
        _row("PRICE", State.REGIME),
        _row("ETF_HOLD", State.REGIME),
        _row("CB_BID", State.HEALTHY),
    ]
    a = classify_regime(CFG, rows, MacroGate.DOVISH)
    assert a.label == Regime.TRANSITION
