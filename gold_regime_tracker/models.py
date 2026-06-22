"""Data model for the Gold Regime Tracker (spec §3).

These dataclasses mirror the records in the spec one-for-one. Every
``IndicatorState`` carries a ``staleness_days`` field; rows older than their
expected cadence x 1.5 are excluded from confirmation counts (§3).
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field, asdict
from datetime import date
from typing import Optional


class State(str, enum.Enum):
    """The three states every voting row is classified into (§1)."""

    HEALTHY = "HEALTHY"
    TRANSITION = "TRANSITION"
    REGIME = "REGIME"


class Regime(str, enum.Enum):
    """The three regime labels the state machine emits (§5)."""

    HEALTHY = "HEALTHY CONSOLIDATION"
    TRANSITION = "TRANSITION / WATCH"
    REGIME = "CONFIRMED REGIME CHANGE"


class MacroGate(str, enum.Enum):
    """Macro overlay does not vote; it gates the others (§5 STEP 3)."""

    HAWKISH = "HAWKISH"   # weights REGIME votes UP
    NEUTRAL = "NEUTRAL"
    DOVISH = "DOVISH"     # weights REGIME votes DOWN (fade the break)


# --- Raw records (§3) ---------------------------------------------------------


@dataclass
class PriceBar:
    date: str
    close: float
    sma21: Optional[float] = None
    sma50: Optional[float] = None
    sma100: Optional[float] = None
    sma200: Optional[float] = None
    dist_200dma_pct: Optional[float] = None


@dataclass
class CotRecord:
    report_date: str          # the Tuesday the report reflects
    fetch_date: str           # when we pulled it (Fri release, 3-day lag §2.1)
    mm_long: int
    mm_short: int
    mm_net: int
    mm_spread: int = 0
    open_interest: int = 0


@dataclass
class EtfRecord:
    month: str                # YYYY-MM
    tonnes: float
    aum_usd: Optional[float] = None
    net_flow_usd: Optional[float] = None
    ytd_flow_usd: Optional[float] = None
    source_tag: str = "semi-auto"


@dataclass
class CbRecord:
    quarter: str              # e.g. 2026-Q1
    reported_net_t: Optional[float] = None
    otc_adjusted_t: Optional[float] = None
    qualitative: str = ""     # firm | rising | softening | cooling
    note: str = ""
    entered_by: str = ""
    entered_on: str = ""      # date the manual journal entry was made


@dataclass
class MacroRecord:
    date: str
    hike_odds_pct: Optional[float] = None
    last_cpi_surprise_bp: Optional[float] = None
    brent_close: Optional[float] = None
    brent_direction: str = ""     # rising | falling | flat
    hormuz_state: str = ""        # calm | tense | escalating
    note: str = ""


# --- Derived / output records (§3) -------------------------------------------


@dataclass
class IndicatorState:
    id: str
    state: State
    value: str                # human-readable current value
    threshold_hit: str        # which rule fired
    as_of: str                # date of the underlying observation
    staleness_days: int
    stale: bool = False       # True => excluded from confirmation counts (§3)
    note: str = ""            # e.g. the MM_NET/MM_SHORT decomposition (§4)
    persisted_periods: int = 1  # consecutive periods held in `state`
    counts: bool = True       # passes persistence + freshness filters (§5)


@dataclass
class RegimeAssessment:
    date: str
    label: Regime
    firing_rows: list = field(default_factory=list)   # ids in TRANSITION/REGIME
    macro_gate: MacroGate = MacroGate.NEUTRAL
    recommendation: str = ""
    confidence: float = 0.0   # fraction of fresh rows agreeing (§6)
    notes: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["label"] = self.label.value
        d["macro_gate"] = self.macro_gate.value
        return d
