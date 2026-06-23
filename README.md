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

# If the live fetch is blocked (Cloudflare / restricted network), download the
# file once in a browser and import it offline:
python -m gold_regime_tracker fetch cot   --file ~/Downloads/fut_disagg_txt_2026.zip
python -m gold_regime_tracker fetch price --file ~/Downloads/xauusd_d.csv

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

The dashboard also carries a **Data sources & freshness** panel: each row's
feed, where it last came from, and when it was fetched, with a fresh/stale dot —
so you can see at a glance whether a verdict is riding on fresh auto-data or a
stale manual one. Fetchers record this automatically; `seed` marks everything as
synthetic-demo.

## Troubleshooting fetches (Cloudflare / restricted networks)

If `fetch cot` / `fetch price` returns **HTTP 403**, the request is being
rejected before it reaches the data — there are two common causes:

- **Real Cloudflare bot filter** (when running locally). The fetchers already
  send browser-like headers; if a host still blocks the default identity, set
  your own: `export GRT_USER_AGENT="Mozilla/5.0 ..."`.
- **A locked-down execution environment** (e.g. Claude Code on the web, CI, a
  corporate proxy). Here *all* outbound requests 403 regardless of headers —
  it is the environment's network policy, not the data host. Run the tool
  somewhere with outbound access, or use the offline import below.

**Offline import — works through any wall.** Download the source once in a
browser (which passes Cloudflare normally) and import the local file:

```bash
# CFTC annual file: https://www.cftc.gov/files/dea/history/fut_disagg_txt_2026.zip
python -m gold_regime_tracker fetch cot   --file fut_disagg_txt_2026.zip

# Stooq daily CSV: https://stooq.com/q/d/l/?s=xauusd&i=d
python -m gold_regime_tracker fetch price --file xauusd_d.csv
```

`--file` accepts the CFTC annual `.zip` or an uncompressed `.txt`/`.csv`, and any
OHLC CSV with a `Date,...,Close` header for price.

## Web dashboard (Cloudflare Pages / any static host)

Cloudflare Pages serves a **static site**, not Python — so the dashboard is
*exported* to plain HTML and Pages serves that. This matches the spec: §6 wants
a single screen you *visit on a schedule*, not a live app.

```bash
python -m gold_regime_tracker seed            # or load real data via fetch/add
python -m gold_regime_tracker export-web --out public
# -> public/index.html  (self-contained, data embedded inline)
#    public/assessment.json
```

A prebuilt `public/` is committed, so the site serves even with no build step.

**Cloudflare Pages setup (fixes the `*.pages.dev` 404):** the 404 means Pages had
nothing static to serve. Point it at `public/`:

- **Config-as-code:** `wrangler.toml` already sets `pages_build_output_dir =
  "./public"`. With Wrangler: `npx wrangler pages deploy public`.
- **Dashboard (Git-connected project):** set **Build output directory** to
  `public`. Leave the build command empty to serve the committed snapshot, or
  set it to regenerate on deploy (runs from the repo checkout — no install
  needed, stdlib only):
  ```
  python3 -m gold_regime_tracker seed && \
  python3 -m gold_regime_tracker export-web --out public --force
  ```

Open `public/index.html` locally to preview — it works over `file://` too.

## Automated weekly refresh (GitHub Actions)

A reload of the deployed page does **not** recompute anything — it's a static
snapshot. To keep it current, [`.github/workflows/weekly.yml`](./.github/workflows/weekly.yml)
runs every Saturday (after Friday's COT release): it fetches the auto rows,
re-runs the assessment, regenerates `public/`, and commits — Cloudflare Pages
then auto-deploys the push.

What it refreshes vs. not:

- **Auto, every week:** `MM_NET`, `MM_SHORT` (CFTC COT), `PRICE` (Stooq), the
  chart + regression/swing analysis, and the `MACRO` hike odds (FedWatch
  methodology — see below).
- **Semi-auto / monthly import:** `ETF_HOLD` (WGC dataset, see below) — import
  the CSV once a month and commit `journal/`.
- **Manual / you maintain:** `CB_BID` (quarterly). Enter it with `add cb …` and
  commit `journal/`. It's hand-entered by design (§2.4) — the highest-weight
  row, and the tool refuses to let auto-data freshness stand in for it.
  (`MACRO`'s CPI surprise and Hormuz state also stay manual; the macro fetch
  preserves whatever you last entered for them.)

### ETF holdings (`fetch etf`)

The WGC "Global gold-backed ETF holdings and flows" dataset has no clean API —
download it from Goldhub, save the sheet as **CSV**, and import:

```bash
python -m gold_regime_tracker fetch etf --file wgc_etf.csv
```

The parser auto-detects the month / tonnes / flow / AUM columns and computes
per-month YTD flow. If it guesses wrong, set the exact headers under
`etf_fetch.columns` in config (and `flow_scale: 1000000` if the file is in USD
millions). Set `etf_fetch.source_url` to a stable CSV URL to also auto-fetch in
CI; left blank, it's import-only (the realistic monthly-manual path).

### MACRO hike odds (`fetch macro`)

The hike/cut odds are derived the way CME FedWatch does it — from **30-Day Fed
Funds futures**, which settle to the average daily effective rate over their
month. A meeting mid-month lets you back out the implied post-meeting rate; for
a late-month meeting the tool uses the next month's contract (whose whole month
is at the post-meeting rate) to avoid a tiny-denominator blow-up.

```bash
python -m gold_regime_tracker fetch macro                 # pull CME settlements
python -m gold_regime_tracker fetch macro --file cme.json  # or import a saved JSON
```

Set your scenario's anchors in `config/thresholds.yaml → macro_fetch`:
`current_target_midpoint` (the current target-rate midpoint), the `fomc_meetings`
calendar (update yearly), and optionally `brent_symbol` for Brent direction. The
odds feed the §5 macro **gate**, not a vote.

GitHub's runners have open internet, so the CFTC/Stooq fetches that 403 inside a
restricted sandbox work there. Notes:

- Scheduled runs execute the workflow on your **default branch**. If Cloudflare
  deploys from a different branch, either make that the default or trigger the
  job manually (Actions → *Weekly refresh* → *Run workflow*) on that branch.
- The workflow pushes with the built-in `GITHUB_TOKEN` (needs *Read and write*
  workflow permissions: Settings → Actions → General).
- If the price fetch fails, the run **skips** the commit rather than publish an
  empty chart.

### Storage model (why there are two folders)

- `data/` — **auto cache** (COT, price). Re-fetched every run; gitignored.
- `journal/` — **tracked** manual entries (`cb`/`etf`/`macro`) and the assessment
  `history` log. Version-controlled, because these are deliberate human
  decisions plus the audit trail the 90-day decision-interval guardrail (§7.1)
  reads — they must survive across ephemeral CI runs.

Both roots can be overridden via `GRT_DATA_DIR` / `GRT_JOURNAL_DIR`.

## Validating the fetchers against real data

The parsers are tested against fixtures that mirror each source's **real
schema** — CFTC's Disaggregated COT text, a Stooq OHLC CSV, the CME settlements
JSON (with its `"Total"` row and `"-"` placeholders), and a WGC export that
carries both regional and total columns (`tests/fixtures/`, exercised by
`tests/test_fixtures.py`). Run `python -m pytest`.

Live HTTP can't be exercised from a locked-down sandbox, so the true end-to-end
check is either: (a) let the **GitHub Action** run on its open-internet runner,
or (b) download each source once in a browser and import it —
`fetch cot --file …`, `fetch price --file …`, `fetch macro --file cme.json`,
`fetch etf --file wgc.csv` — which runs the exact same parsers.

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
