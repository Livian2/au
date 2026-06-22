# Gold Regime Tracker

Decision-support for a **buy-and-hold physical gold position** — not a trading
signal generator. It tracks positioning, fund flows, price structure,
official-sector demand and the macro overlay, and classifies the current
environment as one of:

- **HEALTHY CONSOLIDATION**
- **TRANSITION / WATCH**
- **CONFIRMED REGIME CHANGE**

It is deliberately biased toward **specificity over sensitivity**: it fires
rarely and only on high-conviction, multi-indicator, multi-period,
macro-confirmed shifts. If you find yourself checking it daily, it has failed at
its job. See [`gold_regime_tracker_spec.md`](./gold_regime_tracker_spec.md) for
the full design rationale; section numbers below (§) refer to it.

## Why this is built the way it is

The real intelligence is **not** the data breadth — it is four rules, all of
which are implemented and tested here:

1. **The decomposition rule (§4).** A falling managed-money *net* long is
   ambiguous: longs liquidating (passive exhaustion, often a bottoming tell) vs
   shorts initiating (active down-conviction) look identical in the net number
   and mean opposite things. The tracker always reads `MM_SHORT` alongside
   `MM_NET` and surfaces the decomposition.
2. **The persistence filter (§7.2).** No classification counts toward
   TRANSITION/REGIME unless it has held that state for ≥ 2 of its own periods.
   No single print ever moves the verdict.
3. **The non-negotiable rule (§5).** `CONFIRMED REGIME CHANGE` cannot be
   declared on flow data alone. It requires *either* the `CB_BID` row in REGIME
   (the central-bank floor failing) *or* a sustained hawkish `MACRO` gate. Flows
   leaving while the floor holds is consolidation, by construction.
4. **The guardrails (§7).** 90-day minimum decision interval, weekly recompute
   cap, stale-data confidence penalties, and an anti-anchoring nag on the
   thresholds.

## Indicators (§1)

| ID | Indicator | Cadence | Auto | Weight |
|----|-----------|---------|------|--------|
| `MM_NET`   | CFTC managed-money net long (COMEX gold) | Weekly | Yes | Low–med |
| `MM_SHORT` | CFTC managed-money gross short | Weekly | Yes | Med (conviction tell) |
| `ETF_HOLD` | Global gold-backed ETF tonnes + flow | Monthly | Semi | High |
| `PRICE`    | Spot vs moving averages, weekly close | Daily | Yes | Med |
| `CB_BID`   | Official-sector / OTC demand proxy | Quarterly | Manual | **Highest** |
| `MACRO`    | Hike odds, CPI surprise, Brent/Hormuz | Daily–monthly | Semi | **Gate** |

The two highest-weight rows (`CB_BID`, `MACRO`) are the *least* automatable. The
UI visually distinguishes fresh auto data from stale manual data, and a verdict
computed on a stale `CB_BID` is rendered as a warning, not a clean read.

## Install

Runs on the **Python standard library alone** (Python 3.9+). Optional extras:

```bash
pip install pyyaml   # nicer config parsing (a built-in mini-parser is used otherwise)
pip install pytest   # to run the test suite
```

## Usage

```bash
# Load the June-2026 baseline example data, then see the dashboard:
python -m gold_regime_tracker seed
python -m gold_regime_tracker assess

# Pull the automatable rows (best-effort; degrades gracefully offline):
python -m gold_regime_tracker fetch cot            # CFTC COT, COMEX gold 088691
python -m gold_regime_tracker fetch price          # daily OHLC + SMAs (Stooq xauusd)

# Manual / semi-auto journal entries:
python -m gold_regime_tracker add cb    --quarter 2026-Q1 --qualitative firm --otc 310
python -m gold_regime_tracker add etf   --month 2026-06 --tonnes 4118 --ytd-flow 12.2e9 --net-flow -3e8
python -m gold_regime_tracker add macro --date 2026-06-21 --hike-odds 87 --brent-dir flat --hormuz calm

# Audit how often it cried wolf:
python -m gold_regime_tracker history
```

`assess` honours the weekly recompute cap (§7.3); use `--force` to bypass it for
testing and `--dry-run` to avoid appending to the history log. `--today
YYYY-MM-DD` overrides the clock for what-if analysis.

## Output (§6)

A single, plain-text screen you *visit on a schedule* — no push notifications,
no red/green flashing. It shows the headline regime + confidence (fraction of
fresh rows agreeing), the firing rows with the `MM_NET`/`MM_SHORT`
decomposition, a staleness panel that prominently flags overdue manual rows, a
deliberately boring holder-calibrated recommendation, and a permanent event-risk
disclaimer.

Recommendations:

- `HEALTHY` → "No action. Next scheduled review: [date]."
- `TRANSITION` → "Review only. Do not transact. Re-check after next CB_BID print."
- `REGIME` → "Eligible for a deliberate review of core sizing — subject to the
  §7 minimum interval." (Suppressed entirely if inside the 90-day cooldown.)

## Configuration (§4, §7.6)

Thresholds live in [`config/thresholds.yaml`](./config/thresholds.yaml), never
hardcoded — they drift and get re-anchored each quarter. Update
`last_reanchored` when you re-baseline; if it goes stale (> ~6 months) the
dashboard nags you to re-anchor against current levels.

## Project layout

```
config/thresholds.yaml          # drifting thresholds + cadences (not hardcoded)
gold_regime_tracker/
  models.py                     # the §3 data model
  config.py                     # config loader (+ zero-dep mini-YAML fallback)
  classify.py                   # §4 classification + the decomposition rule
  state_machine.py              # §5 macro gate + non-negotiable rule + confidence
  guardrails.py                 # §7 interval / weekly cap / staleness / anti-anchor
  engine.py                     # wires records -> states -> verdict (persistence)
  store.py                      # JSON record store + assessment history log
  output.py                     # the single-screen renderer
  fetchers/cftc.py              # §2.1 CFTC COT (Phase 1)
  fetchers/price.py             # §2.2 price + SMAs (Phase 1)
  seed.py                       # June-2026 baseline example data
  cli.py                        # command-line interface
tests/                          # the four load-bearing rules, covered
```

## Build phasing (§8)

- **Phase 1 (done):** CFTC fetcher + price/MA + the full state machine,
  classification, guardrails and output, with manual entry for everything else.
  This is ~70% of the value because the decomposition rule and persistence
  filter are the real intelligence.
- **Phase 2:** automated WGC ETF CSV fetcher + macro-odds scrape.
- **Phase 3:** richer structured `CB_BID` journal with WGC-calendar reminders.
- **Out of scope (permanently):** intraday data, price prediction, any
  auto-execution, anything touching a brokerage account. This tool observes; it
  never acts.

## Known limitations (§9 — read before trusting any output)

- The flow rows **lag** (COT is a 3-day-old snapshot); this confirms regimes, it
  does not predict them.
- The leading layer is **macro**, the least clean data here — the tool is
  structurally downstream of its own most important input.
- The highest-weight row (`CB_BID`) updates **quarterly and by hand**; long
  stretches pass with it stale, and the confidence score reflects that.
- It **cannot survive event risk** — a Hormuz/CPI/Fed headline between snapshots
  remaps the board and the tool is silent on exactly the days that matter most.
- It is calibrated to **slow structural drift**, not a 2008/2020-style liquidity
  shock where gold is sold to cover losses elsewhere.

> If the tool ever disagrees with a clear macro regime shift you can see with
> your own eyes, trust the macro and the central-bank read over the flow rows.
> The flows are the confirmation, not the thesis.
