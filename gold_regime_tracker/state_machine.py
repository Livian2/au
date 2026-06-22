"""Regime state machine + macro gate (spec §5).

The non-negotiable rule is enforced here: ``CONFIRMED REGIME CHANGE`` cannot be
declared on flow data alone. It requires *either* the ``CB_BID`` row in REGIME
(the second structural leg failing) *or* a sustained hawkish ``MACRO`` gate.
Flows leaving while the central-bank floor holds is, by construction,
consolidation — not regime change (§5).
"""

from __future__ import annotations

from datetime import date
from typing import Sequence

from .config import Config
from .models import (
    IndicatorState,
    MacroGate,
    MacroRecord,
    Regime,
    RegimeAssessment,
    State,
)

VOTING_IDS = ("MM_NET", "MM_SHORT", "ETF_HOLD", "PRICE", "CB_BID")


def evaluate_macro_gate(cfg: Config, rec: MacroRecord, prior: MacroRecord | None) -> MacroGate:
    """Derive the macro lean (§5 STEP 3). MACRO never votes; it gates."""
    m = cfg["MACRO"]
    hawkish_signals = 0
    dovish_signals = 0

    odds = rec.hike_odds_pct
    if odds is not None:
        rising = prior is not None and prior.hike_odds_pct is not None and odds > prior.hike_odds_pct
        if odds >= m["hawkish_hike_odds_min"] and (rising or prior is None):
            hawkish_signals += 1
        elif prior is not None and prior.hike_odds_pct is not None and odds < prior.hike_odds_pct:
            dovish_signals += 1

    if rec.last_cpi_surprise_bp is not None:
        if rec.last_cpi_surprise_bp >= m["hot_cpi_surprise_bp"]:
            hawkish_signals += 1
        elif rec.last_cpi_surprise_bp <= -m["hot_cpi_surprise_bp"]:
            dovish_signals += 1

    direction = (rec.brent_direction or "").lower()
    hormuz = (rec.hormuz_state or "").lower()
    if direction == "rising" or hormuz in ("tense", "escalating"):
        hawkish_signals += 1
    elif direction == "falling" and hormuz in ("calm", ""):
        dovish_signals += 1

    if hawkish_signals > dovish_signals:
        return MacroGate.HAWKISH
    if dovish_signals > hawkish_signals:
        return MacroGate.DOVISH
    return MacroGate.NEUTRAL


def apply_persistence(states: Sequence[IndicatorState], cfg: Config) -> None:
    """Mark whether each row counts toward TRANSITION/REGIME (§5 STEP 2, §7.2).

    A row counts only if it is fresh AND (HEALTHY, or has held its
    TRANSITION/REGIME state for >= persistence_periods). ``persisted_periods``
    must be populated by the caller from the history log.
    """
    need = int(cfg["state_machine"]["persistence_periods"])
    for s in states:
        if s.stale:
            s.counts = False
            continue
        if s.state == State.HEALTHY:
            s.counts = True
        else:
            s.counts = s.persisted_periods >= need


def classify_regime(
    cfg: Config,
    states: Sequence[IndicatorState],
    macro_gate: MacroGate,
    macro_stale: bool = False,
) -> RegimeAssessment:
    """§5 STEP 1–4 + the non-negotiable rule."""
    apply_persistence(states, cfg)
    fresh = [s for s in states if not s.stale]
    counting = [s for s in fresh if s.counts]

    transition_rows = [s for s in counting if s.state == State.TRANSITION]
    regime_rows = [s for s in counting if s.state == State.REGIME]
    # A REGIME row also satisfies a TRANSITION threshold for counting purposes.
    transition_or_worse = transition_rows + regime_rows

    sm = cfg["state_machine"]
    notes: list[str] = []
    warnings: list[str] = []

    cb_in_regime = any(s.id == "CB_BID" and s.state == State.REGIME and s.counts for s in fresh)
    hawkish = macro_gate == MacroGate.HAWKISH and not macro_stale

    # §5 STEP 3 — macro gate weighting note.
    if macro_gate == MacroGate.HAWKISH:
        notes.append("MACRO hawkish: REGIME votes weighted UP (scenario that can break two legs at once).")
    elif macro_gate == MacroGate.DOVISH:
        notes.append("MACRO dovish: REGIME votes weighted DOWN — treat flow weakness as consolidation, fade the break.")

    n_regime = len(regime_rows)
    n_trans = len(transition_or_worse)

    # §5 STEP 4 classification.
    label = Regime.HEALTHY
    confirmed_regime = (
        n_regime >= sm["regime_min_rows"] and (cb_in_regime or hawkish)
    )

    if confirmed_regime:
        label = Regime.REGIME
    elif n_trans >= sm["transition_min_rows"] or (n_regime >= 2 and not cb_in_regime):
        label = Regime.TRANSITION
    else:
        label = Regime.HEALTHY

    # Non-negotiable rule guardrail (§5): never let flows alone declare REGIME.
    if n_regime >= sm["regime_min_rows"] and not (cb_in_regime or hawkish):
        label = Regime.TRANSITION
        warnings.append(
            "REGIME thresholds met on flow rows, but CB_BID floor holds and MACRO "
            "is not hawkish — by construction this is consolidation, not regime "
            "change. Held at TRANSITION (§5 non-negotiable rule)."
        )

    # §5 STEP 3 dovish fade: soften a borderline REGIME when macro is easing.
    if label == Regime.REGIME and macro_gate == MacroGate.DOVISH and not cb_in_regime:
        label = Regime.TRANSITION
        warnings.append("MACRO dovish gate fades a flow-driven break to TRANSITION (§5 STEP 3).")

    firing = [s.id for s in transition_or_worse]
    confidence = _confidence(fresh, label, macro_stale)

    return RegimeAssessment(
        date="",  # set by caller
        label=label,
        firing_rows=firing,
        macro_gate=macro_gate,
        recommendation="",  # set by guardrails/output layer
        confidence=confidence,
        notes=notes,
        warnings=warnings,
    )


def _confidence(fresh: Sequence[IndicatorState], label: Regime, macro_stale: bool) -> float:
    """Confidence = fraction of fresh rows agreeing with the label (§6),
    reduced when high-weight manual rows are stale (§7.4)."""
    if not fresh:
        return 0.0
    target = {
        Regime.HEALTHY: State.HEALTHY,
        Regime.TRANSITION: State.TRANSITION,
        Regime.REGIME: State.REGIME,
    }[label]
    if label == Regime.TRANSITION:
        agree = sum(1 for s in fresh if s.state in (State.TRANSITION, State.REGIME))
    else:
        agree = sum(1 for s in fresh if s.state == target)
    conf = agree / len(fresh)

    # §7.4: stale CB_BID or stale macro reduces, never maintains, confidence.
    cb_present = any(s.id == "CB_BID" for s in fresh)
    if not cb_present:
        conf *= 0.6
    if macro_stale:
        conf *= 0.8
    return round(conf, 2)
