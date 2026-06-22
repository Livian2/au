"""Single-screen summary renderer (spec §6).

Deliberately plain text. No colour flashing, no push notifications — a page you
visit on a schedule, not one that pings you (§6, §7). Stale rows are clearly
marked; manual rows flagged when overdue; a stale CB_BID downgrades a clean
verdict to a warning.
"""

from __future__ import annotations

from datetime import date
from typing import Sequence

from .config import Config
from .guardrails import EVENT_RISK_DISCLAIMER, reanchor_nag
from .models import IndicatorState, RegimeAssessment, State

_MANUAL_ROWS = {"CB_BID"}
_BAR = "=" * 72
_RULE = "-" * 72


def _state_tag(s: IndicatorState) -> str:
    if s.stale:
        return "STALE"
    return s.state.value


def render(
    cfg: Config,
    assessment: RegimeAssessment,
    states: Sequence[IndicatorState],
    today: date,
    blocked_until=None,
) -> str:
    lines: list[str] = []
    lines.append(_BAR)
    lines.append(f"  GOLD REGIME TRACKER — assessment for {today.isoformat()}")
    lines.append(_BAR)

    if blocked_until is not None:
        lines.append(
            f"  [weekly cap §7.3] Assessment already ran this week. Next recompute: "
            f"{blocked_until.isoformat()}. Showing the standing verdict; do not "
            "recompute to watch the tape."
        )
        lines.append(_RULE)

    # Headline
    conf_pct = int(round(assessment.confidence * 100))
    lines.append(f"  REGIME: {assessment.label.value}")
    lines.append(f"  Confidence: {conf_pct}%   (fraction of fresh rows agreeing)")
    lines.append(f"  Macro gate: {assessment.macro_gate.value}")
    lines.append("")
    lines.append(f"  RECOMMENDATION: {assessment.recommendation}")
    lines.append(_RULE)

    # Indicator table
    lines.append("  ROWS")
    for s in states:
        flag = "  (MANUAL)" if s.id in _MANUAL_ROWS else ""
        persist = f" persisted={s.persisted_periods}p" if s.state != State.HEALTHY else ""
        count = "" if s.counts else "  [does not count]"
        lines.append(f"    {s.id:<9} {_state_tag(s):<11}{flag}")
        lines.append(f"        value : {s.value}")
        lines.append(f"        rule  : {s.threshold_hit}")
        lines.append(f"        as-of : {s.as_of}  (age {s.staleness_days}d){persist}{count}")
        if s.note:
            lines.append(f"        note  : {s.note}")
    lines.append(_RULE)

    # Firing rows
    if assessment.firing_rows:
        lines.append(f"  FIRING (TRANSITION/REGIME, counting): {', '.join(assessment.firing_rows)}")
    else:
        lines.append("  FIRING: none")

    # Staleness panel — flag overdue manual rows prominently
    overdue_manual = [s for s in states if s.id in _MANUAL_ROWS and s.stale]
    if overdue_manual:
        lines.append("")
        for s in overdue_manual:
            lines.append(
                f"  ** STALE MANUAL ROW: {s.id} is {s.staleness_days}d old — verdict "
                "carries a warning, not a clean read (§6). **"
            )

    # Notes & warnings
    for n in assessment.notes:
        lines.append(f"  - note: {n}")
    for w in assessment.warnings:
        lines.append(f"  ! WARN: {w}")

    nag = reanchor_nag(cfg, today)
    if nag:
        lines.append(f"  ! ANTI-ANCHORING: {nag}")

    lines.append(_RULE)
    lines.append(f"  {EVENT_RISK_DISCLAIMER}")
    lines.append(_BAR)
    return "\n".join(lines)
