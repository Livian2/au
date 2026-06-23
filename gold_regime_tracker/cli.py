"""Command-line interface (spec §6, §8).

Subcommands:
  assess            Run the weekly assessment and render the single-screen summary.
  fetch cot|price   Pull and store the automatable rows (§2.1, §2.2).
  add cb|macro|etf  Make a manual / semi-auto journal entry (§2.3, §2.4, §2.5).
  history           Print the audit log of past assessments (§6).
  seed              Load the June-2026 baseline example data for a dry run.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, timezone

from . import store
from .config import load_config
from .engine import assess
from .models import CbRecord, EtfRecord, MacroRecord
from .output import render
from .seed import seed_baseline


def _today(args) -> date:
    return date.fromisoformat(args.today) if getattr(args, "today", None) else date.today()


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def cmd_assess(args) -> int:
    cfg = load_config(args.config)
    today = _today(args)
    assessment, states, cb_stale, blocked = assess(cfg, today, force=args.force)
    print(render(cfg, assessment, states, today, blocked_until=blocked))
    if not blocked and not args.dry_run:
        store.append_history(assessment)
    return 0


def cmd_fetch(args) -> int:
    if args.source == "cot":
        from .fetchers import cftc

        try:
            recs = cftc.from_file(args.file) if args.file else cftc.fetch_year(args.year)
        except (cftc.FetchError, OSError) as exc:
            print(f"[fetch cot] {exc}")
            return 1
        if not recs:
            print("[fetch cot] no COMEX gold rows found in source.")
            return 1
        for r in recs:
            store.save_cot(r)
        src = f"file {args.file}" if args.file else f"year {args.year or 'current'}"
        store.record_source("cot", "CFTC Disaggregated COT (COMEX gold 088691)",
                            _now_iso(), detail=f"{'import' if args.file else 'live'}; latest report {recs[-1].report_date}")
        print(f"[fetch cot] stored {len(recs)} COT record(s) from {src}; latest {recs[-1].report_date}.")
    elif args.source == "price":
        from .fetchers import price

        try:
            bars = price.from_file(args.file) if args.file else price.fetch(args.symbol)
        except (price.FetchError, OSError) as exc:
            print(f"[fetch price] {exc}")
            return 1
        for b in bars[-260:]:  # keep ~1y of daily bars
            store.save_price(b)
        label = {"file": "Imported OHLC CSV", "stooq": f"Stooq {args.symbol}"}.get(bars[-1].source, bars[-1].source or "price feed")
        store.record_source("price", label, _now_iso(), detail=f"latest close {bars[-1].date}")
        print(f"[fetch price] stored {min(len(bars),260)} bar(s); latest {bars[-1].date} close={bars[-1].close}.")
    elif args.source == "macro":
        return _fetch_macro(args)
    elif args.source == "etf":
        return _fetch_etf(args)
    return 0


def _fetch_etf(args) -> int:
    from .fetchers import wgc

    cfg = load_config(args.config)
    try:
        recs = wgc.from_file(args.file, cfg) if args.file else wgc.fetch(cfg)
    except (wgc.FetchError, OSError) as exc:
        print(f"[fetch etf] {exc}")
        return 1
    for r in recs:
        store.save_etf(r)
    last = recs[-1]
    store.record_source("etf", "WGC Goldhub ETF holdings & flows", _now_iso(),
                        detail=f"{'import' if args.file else 'live'}; latest month {last.month}")
    print(f"[fetch etf] stored {len(recs)} month(s); latest {last.month}: "
          f"{last.tonnes}t, ytd_flow={last.ytd_flow_usd}.")
    return 0


def _fetch_macro(args) -> int:
    from .fetchers import fedwatch

    cfg = load_config(args.config)
    today = _today(args)
    try:
        settl = fedwatch.from_file(args.file) if args.file else fedwatch.fetch_settlements(cfg)
    except (fedwatch.FetchError, OSError) as exc:
        print(f"[fetch macro] {exc}")
        return 1
    res = fedwatch.compute(cfg, today, settl)
    if res is None:
        print("[fetch macro] no upcoming FOMC meeting in config, or no matching contract month in the data.")
        return 1

    # Optional Brent direction (last close vs ~4 weeks prior).
    brent_close, brent_dir = None, ""
    symbol = (cfg.get("macro_fetch") or {}).get("brent_symbol") or ""
    if symbol:
        try:
            from .fetchers import price as pricef

            bars = pricef.fetch(symbol)
            if len(bars) >= 21:
                brent_close = bars[-1].close
                brent_dir = "rising" if bars[-1].close > bars[-21].close else "falling" if bars[-1].close < bars[-21].close else "flat"
        except Exception as exc:  # Brent is a nice-to-have; never fail the row on it
            print(f"[fetch macro] brent skipped: {exc}")

    # Merge: preserve the manual fields (CPI surprise, Hormuz) from the last entry.
    prev = max(store.load_macro(), key=lambda r: r.date, default=None)
    rec = MacroRecord(
        date=today.isoformat(),
        hike_odds_pct=res["hike_odds_pct"],
        last_cpi_surprise_bp=(prev.last_cpi_surprise_bp if prev else None),
        brent_close=(brent_close if brent_close is not None else (prev.brent_close if prev else None)),
        brent_direction=(brent_dir or (prev.brent_direction if prev else "")),
        hormuz_state=(prev.hormuz_state if prev else ""),
        note=(f"FedWatch-implied for {res['meeting']} ({res['method']}): hike "
              f"{res['hike_odds_pct']}% (implied {res['implied_change_bp']:+}bp to "
              f"{res['implied_end_rate']}%). CPI/Hormuz preserved from last manual entry."),
    )
    store.save_macro(rec)
    store.record_source("macro", "CME FedWatch (30-Day Fed Funds futures)", _now_iso(),
                        detail=f"{'import' if args.file else 'live'}; next FOMC {res['meeting']} ({res['method']})")
    print(f"[fetch macro] {res['meeting']}: hike odds {res['hike_odds_pct']}% "
          f"(implied {res['implied_change_bp']:+}bp). Saved.")
    return 0


def cmd_add(args) -> int:
    if args.kind == "cb":
        rec = CbRecord(
            quarter=args.quarter,
            reported_net_t=args.reported,
            otc_adjusted_t=args.otc,
            qualitative=args.qualitative,
            note=args.note or "",
            entered_by=args.by or "",
            entered_on=date.today().isoformat(),
        )
        store.save_cb(rec)
        store.record_source("cb", "Manual journal (WGC Gold Demand Trends)", _now_iso(),
                            detail=f"{args.quarter} entered by {args.by or 'unknown'}")
        print(f"[add cb] saved {args.quarter}: {args.qualitative}")
    elif args.kind == "macro":
        rec = MacroRecord(
            date=args.date,
            hike_odds_pct=args.hike_odds,
            last_cpi_surprise_bp=args.cpi_bp,
            brent_close=args.brent,
            brent_direction=args.brent_dir or "",
            hormuz_state=args.hormuz or "",
            note=args.note or "",
        )
        store.save_macro(rec)
        print(f"[add macro] saved {args.date}")
    elif args.kind == "etf":
        rec = EtfRecord(
            month=args.month,
            tonnes=args.tonnes,
            aum_usd=args.aum,
            net_flow_usd=args.net_flow,
            ytd_flow_usd=args.ytd_flow,
            source_tag=args.source_tag or "semi-auto",
        )
        store.save_etf(rec)
        print(f"[add etf] saved {args.month}: {args.tonnes}t")
    return 0


def cmd_history(args) -> int:
    rows = store.load_history()
    if not rows:
        print("No assessments logged yet.")
        return 0
    for h in rows:
        print(
            f"{h['date']}  {h['label']:<24} conf={int(h.get('confidence',0)*100):>3}%  "
            f"gate={h.get('macro_gate')}  firing={','.join(h.get('firing_rows') or []) or '-'}"
        )
    return 0


def cmd_export_web(args) -> int:
    cfg = load_config(args.config)
    today = _today(args)
    from .webexport import build_site

    path = build_site(cfg, args.out, today, force=args.force)
    print(f"[export-web] wrote {path} (+ assessment.json). Publish dir: {args.out}")
    return 0


def cmd_seed(args) -> int:
    n = seed_baseline()
    print(f"[seed] loaded baseline example data ({n} records). Run `assess` to see the dashboard.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="gold-regime", description=__doc__)
    p.add_argument("--config", default=None, help="path to thresholds.yaml")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("assess", help="run the weekly assessment")
    a.add_argument("--today", help="override 'today' (YYYY-MM-DD) for testing")
    a.add_argument("--force", action="store_true", help="bypass the §7.3 weekly cap")
    a.add_argument("--dry-run", action="store_true", help="do not append to history log")
    a.set_defaults(func=cmd_assess)

    f = sub.add_parser("fetch", help="pull automatable rows (or import a local file)")
    f.add_argument("source", choices=["cot", "price", "macro", "etf"])
    f.add_argument("--year", type=int, default=None)
    f.add_argument("--symbol", default="xauusd")
    f.add_argument("--today", default=None, help="override 'today' (YYYY-MM-DD), used by macro")
    f.add_argument(
        "--file",
        default=None,
        help="import from a locally-downloaded file instead of fetching "
        "(cot: annual .zip or .txt/.csv; price: OHLC .csv; macro: CME "
        "settlements .json; etf: WGC holdings .csv). Sidesteps "
        "Cloudflare/network blocks.",
    )
    f.set_defaults(func=cmd_fetch)

    ad = sub.add_parser("add", help="manual journal entry")
    adsub = ad.add_subparsers(dest="kind", required=True)

    cb = adsub.add_parser("cb", help="central-bank bid quarterly entry")
    cb.add_argument("--quarter", required=True, help="e.g. 2026-Q1")
    cb.add_argument("--qualitative", required=True, choices=["firm", "rising", "softening", "cooling"])
    cb.add_argument("--reported", type=float, default=None)
    cb.add_argument("--otc", type=float, default=None)
    cb.add_argument("--note", default=None)
    cb.add_argument("--by", default=None)
    cb.set_defaults(func=cmd_add, kind="cb")

    mc = adsub.add_parser("macro", help="macro overlay entry")
    mc.add_argument("--date", required=True, help="YYYY-MM-DD")
    mc.add_argument("--hike-odds", type=float, default=None, dest="hike_odds")
    mc.add_argument("--cpi-bp", type=float, default=None, dest="cpi_bp")
    mc.add_argument("--brent", type=float, default=None)
    mc.add_argument("--brent-dir", choices=["rising", "falling", "flat"], default=None, dest="brent_dir")
    mc.add_argument("--hormuz", choices=["calm", "tense", "escalating"], default=None)
    mc.add_argument("--note", default=None)
    mc.set_defaults(func=cmd_add, kind="macro")

    et = adsub.add_parser("etf", help="ETF holdings entry")
    et.add_argument("--month", required=True, help="YYYY-MM")
    et.add_argument("--tonnes", type=float, required=True)
    et.add_argument("--aum", type=float, default=None)
    et.add_argument("--net-flow", type=float, default=None, dest="net_flow")
    et.add_argument("--ytd-flow", type=float, default=None, dest="ytd_flow")
    et.add_argument("--source-tag", default=None, dest="source_tag")
    et.set_defaults(func=cmd_add, kind="etf")

    h = sub.add_parser("history", help="print the assessment audit log")
    h.set_defaults(func=cmd_history)

    s = sub.add_parser("seed", help="load June-2026 baseline example data")
    s.set_defaults(func=cmd_seed)

    w = sub.add_parser("export-web", help="render the dashboard to a static site (Cloudflare Pages)")
    w.add_argument("--out", default="public", help="output directory (default: public)")
    w.add_argument("--today", help="override 'today' (YYYY-MM-DD)")
    w.add_argument("--force", action="store_true", help="bypass the §7.3 weekly cap")
    w.set_defaults(func=cmd_export_web)

    return p


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
