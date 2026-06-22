# Gold Regime Tracker — Program Specification

**Purpose:** Track the developing structural picture for gold (positioning, fund flows, price structure, official-sector demand, and the macro overlay) and classify the current environment as **Healthy Consolidation**, **Transition / Watch**, or **Confirmed Regime Change** — calibrated for a *physical holder* with a long horizon, not a trader.

**Design owner:** Ole
**Status:** v0.1 spec — language-agnostic. Build in whatever stack you prefer (Python is the path of least resistance for the data sources below).
**Last updated baseline:** June 2026 (thresholds anchored to prints current as of ~June 22, 2026).

---

## 0. The one thing this spec must not become

This program is **decision-support for a buy-and-hold physical position**, not a trading signal generator. Every design choice below is biased toward **specificity over sensitivity**: it should fire rarely and only on high-conviction, multi-indicator, multi-period, macro-confirmed shifts. A trader tunes for sensitivity (catch every move early, accept false positives). A physical holder tunes for the opposite (few false positives, accept lag), because the only available actions are rare: *add on structural weakness*, *hold*, or *trim a long-term core*. None of those should ever be triggered by a single week of data.

If you ever find yourself checking this dashboard daily, the program has failed at its job and is now feeding an anxiety loop. Build the guardrails in Section 7 first, not last.

---

## 1. Indicators tracked

Six rows, mapped from the confirmation grid. Each is classified independently into one of three states, then combined by the state machine in Section 5.

| ID | Indicator | Source cadence | Auto-fetchable? | Weight (physical horizon) |
|----|-----------|----------------|-----------------|---------------------------|
| `MM_NET` | CFTC managed-money net long (COMEX gold) | Weekly | Yes (clean) | Low–medium |
| `MM_SHORT` | CFTC managed-money **gross short** | Weekly | Yes (clean) | Medium (best conviction tell) |
| `ETF_HOLD` | Global gold-backed ETF tonnes + monthly flow | Monthly | Partial (CSV scrape) | High |
| `PRICE` | Spot vs key moving averages, weekly close | Daily | Yes (clean) | Medium |
| `CB_BID` | Official-sector / OTC / Swiss-refinery demand proxy | Quarterly | No (manual) | **Highest** |
| `MACRO` | Hike odds, CPI surprise, Brent direction | Daily–monthly | Partial | **Gate** (see §5) |

> **Honesty flag baked into the schema:** the two highest-weight rows (`CB_BID`, `MACRO`) are the *least* automatable. Do not let the program's confidence be driven by the rows that happen to have clean APIs. The UI must visually distinguish "fresh auto data" from "stale manual data" (see §6).

---

## 2. Data sources & access methods

### 2.1 CFTC COT — `MM_NET`, `MM_SHORT` (automatable)
- **Source:** CFTC Commitments of Traders, *Disaggregated Futures-Only* report.
- **Contract:** COMEX Gold, 100 troy oz, CFTC code **088691**.
- **Access:** CFTC publishes weekly text/CSV plus compressed annual historical files. Pull the annual bulk file and append the weekly release.
- **Release:** Fridays 15:30 ET, reflecting the prior **Tuesday** close (3-day lag — bake this into timestamps).
- **Fields needed:** `managed_money_long`, `managed_money_short`, `managed_money_spreading`, `open_interest`, `report_date`.
- **Derived:** `mm_net = managed_money_long - managed_money_short`.

### 2.2 Price & moving averages — `PRICE` (automatable)
- **Series:** spot XAU/USD or front-month COMEX future (`GC=F`) — pick one and be consistent.
- **Source options:** any metals/markets API or daily OHLC feed you already trust (Stooq, a metals API, or your IBKR data). Avoid scraping forecast blogs — you want raw price only.
- **Computed:** 21/50/100/200-day simple moving averages; weekly close; distance-to-200DMA in %.
- **Reference levels (June 2026, update as they drift):** 200DMA ≈ $4,340; structural support shelf ≈ $4,300; next support ≈ $3,800; overhead resistance band ≈ $4,470–$4,530.

### 2.3 ETF holdings & flows — `ETF_HOLD` (semi-automatable)
- **Source:** World Gold Council Goldhub — "Global gold-backed ETF holdings and flows" dataset (downloadable CSV, updated monthly; partial weekly).
- **Fields:** total tonnes, AUM, monthly net flow (USD), regional breakdown, YTD cumulative flow.
- **Access reality:** no clean public API. Build a small scheduled fetcher for the CSV, or accept monthly manual download. Flag the record as `source: semi-auto`.
- **Reference (June 2026):** holdings 4,121t; record 4,176t (27 Feb 2026); YTD flow +~$17bn; May = −$2bn (first material outflow of the year).

### 2.4 Official-sector bid — `CB_BID` (manual)
- **Source:** WGC *Gold Demand Trends* (quarterly) + monthly central-bank statistics; cross-check with Swiss refinery export data and UK/London vault flow commentary (the WGC notes official trade data under-captures sovereign buying since Aug 2025).
- **Access reality:** **no automation.** This is a quarterly manual journal entry. Record: reported net purchases (t), WGC OTC-adjusted estimate (t), notable buyers/sellers, and a one-line qualitative read (`firm` / `softening` / `cooling`).
- **Why it's weighted highest:** it's the price-inelastic structural floor under your thesis. It is also the slowest to move and the slowest to observe — which is exactly why it's a *physical holder's* signal and not a trader's.

### 2.5 Macro overlay — `MACRO` (semi-automatable, used as a gate)
- **Hike/cut odds:** CME FedWatch implied probabilities (scrape or manual). Baseline June 2026: ~85–89% implied for a December hike.
- **Inflation surprise:** BLS CPI release vs consensus (manual or calendar-API).
- **Oil:** Brent direction (auto). Tie to the Strait of Hormuz / Iran-deal headline state — this is the swing variable converting geopolitics into the rate channel.
- **Role:** does not get a Healthy/Transition/Regime vote of its own. It **gates** the others (§5).

---

## 3. Data model

```
PriceBar       { date, close, sma21, sma50, sma100, sma200, dist_200dma_pct }
CotRecord      { report_date, fetch_date, mm_long, mm_short, mm_net, mm_spread, open_interest }
EtfRecord      { month, tonnes, aum_usd, net_flow_usd, ytd_flow_usd, source_tag }
CbRecord       { quarter, reported_net_t, otc_adjusted_t, qualitative, note, entered_by }   # manual
MacroRecord    { date, hike_odds_pct, last_cpi_surprise_bp, brent_close, hormuz_state, note }
IndicatorState { id, state ∈ {HEALTHY, TRANSITION, REGIME}, value, threshold_hit, as_of, staleness_days }
RegimeAssessment { date, label, firing_rows[], macro_gate, recommendation, confidence }
```

Every `IndicatorState` carries a **`staleness_days`** field. Any row older than its expected cadence × 1.5 is rendered greyed-out and **excluded from confirmation counts** until refreshed.

---

## 4. Indicator classification rules

Thresholds anchored to June 2026 baselines. Store them in a **config file**, not hardcoded — they drift, and you'll re-anchor every few quarters.

```yaml
MM_NET:            # managed-money net long, contracts
  healthy:    ">= 70000"          # no sustained bleed; baseline ~106k
  transition: "50000 to 70000 with falling open_interest"
  regime:     "< 50000 toward flat/negative"

MM_SHORT:          # managed-money GROSS short — the conviction tell
  healthy:    "< 35000"           # baseline ~20k
  transition: "35000 to 55000"
  regime:     ">= 55000 and rising"   # funds actively short, not just unwinding longs

ETF_HOLD:          # global tonnes + flow persistence
  healthy:    "tonnes >= 4000 and ytd_flow > 0"
  transition: "tonnes 3900 to 4000, 2-3 consecutive monthly outflows"
  regime:     "tonnes < 3900 with accelerating outflows and ytd_flow < 0"

PRICE:             # weekly close vs structure
  healthy:    "weekly_close > 4300 (above ~200DMA)"
  transition: "weekly_close 4300 to 4530 (choppy, capped)"
  regime:     "decisive weekly close < 4300"     # opens 3800

CB_BID:            # manual quarterly
  healthy:    "otc_adjusted firm or rising"
  transition: "intensity softening q/q"
  regime:     "visibly cooling — second leg failing"
```

**Critical interpretation rule — read components, not the headline net.**
A falling `MM_NET` is ambiguous: it can mean *longs liquidating* (passive exhaustion — often a bottoming tell) or *shorts initiating* (active down-conviction). These look identical in the net number and mean opposite things. The program must always evaluate `MM_SHORT` alongside `MM_NET` and surface the decomposition. Rising gross shorts is the only thing in the dataset resembling a conviction signal.

---

## 5. Regime state machine

```
INPUTS: the 5 voting rows (MM_NET, MM_SHORT, ETF_HOLD, PRICE, CB_BID) + MACRO gate

STEP 1 — Count fresh (non-stale) rows in each state.
STEP 2 — Apply persistence filter:
         a row only "counts" toward TRANSITION/REGIME if it has held that
         state for >= 2 consecutive observation periods (its own cadence).
STEP 3 — Apply the MACRO gate:
         - MACRO hawkish (hike odds rising, CPI hot, Brent/Hormuz inflationary)
             -> REGIME votes are weighted UP; this is the scenario that can
                break two legs at once (Western flows out AND CB bid cooling).
         - MACRO dovish/easing (deal holds, oil falls, cuts re-priced)
             -> REGIME votes are weighted DOWN; treat flow weakness as
                consolidation, fade the break.
STEP 4 — Classify:
         HEALTHY CONSOLIDATION : < 3 rows in TRANSITION/REGIME after filtering
         TRANSITION / WATCH    : >= 3 rows TRANSITION, OR 2 REGIME without CB_BID
         CONFIRMED REGIME CHANGE: >= 3 rows REGIME (must include CB_BID OR a
                                   hawkish MACRO gate) persisting >= 2 periods
```

**Non-negotiable rule:** `CONFIRMED REGIME CHANGE` cannot be declared on flow data alone. It requires *either* the `CB_BID` row in REGIME (the second structural leg failing) *or* a sustained hawkish `MACRO` gate. Flows leaving while the central-bank floor holds is, by construction, consolidation — not regime change. This is the whole point of the tool; do not let it shortcut.

---

## 6. Output

Single-screen summary, refreshed no more often than weekly:

- **Headline:** current regime label + confidence (= fraction of fresh rows agreeing).
- **Firing rows:** which indicators are in TRANSITION/REGIME, with the decomposition note for `MM_NET`/`MM_SHORT`.
- **Staleness panel:** every row with an as-of date; manual rows (`CB_BID`) prominently flagged when overdue. **A regime label computed with a stale `CB_BID` row must display a warning, not a clean verdict.**
- **Recommendation field** — calibrated to the holder, deliberately boring:
  - `HEALTHY` → "No action. Next scheduled review: [date]."
  - `TRANSITION` → "Review only. Do not transact. Re-check after next CB_BID print."
  - `REGIME` → "Eligible for a deliberate review of core sizing — subject to the §7 minimum interval."
- **History log:** append every weekly assessment so you can audit how often it cried wolf.

No push notifications. No red/green flashing. The output is a page you *visit on a schedule*, not one that pings you.

---

## 7. Guardrails (build these first)

These are load-bearing, not optional polish.

1. **Minimum decision interval:** the program must refuse to surface a second "act-eligible" recommendation within **90 days** of the last one, regardless of data. Physical decisions are quarterly at most.
2. **No single-print actions:** any TRANSITION/REGIME classification requires the 2-period persistence filter. Hard-coded; not user-overridable in the main view.
3. **Weekly cap on dashboard refresh:** even if data is fresher, the assessment recomputes on a weekly schedule. Removes the temptation to watch the tape.
4. **Stale-data honesty:** the confidence score is *reduced*, not maintained, when high-weight manual rows go stale. A confident verdict on auto-data alone is a false verdict.
5. **Event-risk disclaimer in the UI:** a permanent footer noting the tracker is silent between snapshots and cannot price a gap move on a Hormuz/CPI/Fed headline. The tool is for trend confirmation, not event protection.
6. **Anti-anchoring:** thresholds live in config and carry a "last re-anchored" date. If that date is >6 months old, the UI nags you to re-baseline against current levels rather than June-2026 ones.

---

## 8. Suggested build phasing

- **Phase 1 (highest value / lowest effort):** CFTC fetcher (`MM_NET`, `MM_SHORT`) + price/MA + the state machine with manual entry for everything else. This alone delivers ~70% of the value, because the decomposition rule and the persistence filter are the real intelligence — not the data breadth.
- **Phase 2:** WGC ETF CSV fetcher + macro odds scrape.
- **Phase 3:** structured manual-entry journal for `CB_BID` with reminders tied to the WGC quarterly publication calendar.
- **Explicitly out of scope:** intraday data, price prediction, any auto-execution, anything touching your IBKR account. This tool observes; it never acts.

---

## 9. Known limitations (read before trusting any output)

- **The flow rows lag.** COT is a 3-day-old snapshot; positioning follows price. This tool confirms regimes, it does not predict them.
- **The leading layer is macro,** which is the least clean data here. The tool is structurally downstream of its own most important input.
- **The highest-weight row updates quarterly and by hand.** Long stretches will pass with a stale `CB_BID`; the confidence score must reflect that, and you must resist treating auto-data freshness as analytical confidence.
- **It cannot survive event risk.** A headline between snapshots remaps the board and the tool is silent on exactly the days that matter most.
- **It is calibrated to one regime type** (slow structural drift). A 2020/2008-style liquidity shock — where gold gets sold to cover losses elsewhere regardless of fundamentals — will not be caught cleanly by these thresholds.

If the tool ever disagrees with a clear macro regime shift you can see with your own eyes, trust the macro and the central-bank read over the flow rows. The flows are the confirmation, not the thesis.
