"""Static-site exporter (spec §6) for Cloudflare Pages / any static host.

Renders the weekly assessment to a single self-contained ``index.html`` (data and
the SVG chart embedded inline — no fetch, no API, works over file://) plus a
sidecar ``assessment.json``. Deliberately calm: no flashing, no auto-refresh, no
push — a page you visit on a schedule, not one that pings you.
"""

from __future__ import annotations

import html
import json
import os
from datetime import date

from . import store
from .analysis import SwingLevels, TrendChannel, swing_levels, trend_channel
from .charts import render_price_chart
from .config import Config
from .engine import assess
from .guardrails import EVENT_RISK_DISCLAIMER, reanchor_nag
from .models import IndicatorState, RegimeAssessment, State

_MANUAL_ROWS = {"CB_BID"}
_ACCENT = "#c9a14a"

_REGIME_CLASS = {
    "HEALTHY CONSOLIDATION": "healthy",
    "TRANSITION / WATCH": "transition",
    "CONFIRMED REGIME CHANGE": "regime",
}
_STATE_CLASS = {
    State.HEALTHY: "healthy",
    State.TRANSITION: "transition",
    State.REGIME: "regime",
}


def _esc(value) -> str:
    return html.escape(str(value), quote=True)


_ARROW = {"up": "▲", "down": "▼", "": ""}


def _value_cell(s: IndicatorState) -> str:
    if not s.primary_value:
        return f'<span class="mono">{_esc(s.value)}</span>'
    chips = "".join(
        f'<span class="chip"><span class="chip-k">{_esc(k)}</span>'
        f'<span class="chip-v mono">{_esc(v)}</span></span>'
        for k, v in s.chips
    )
    delta = ""
    if s.delta:
        arrow = _ARROW.get(s.delta_dir, "")
        delta = f'<span class="delta {_esc(s.delta_dir)}">{arrow} {_esc(s.delta)}</span>'
    return f"""
        <div class="v-head"><span class="v-primary mono">{_esc(s.primary_value)}</span>{delta}</div>
        <div class="v-label">{_esc(s.primary_label)}</div>
        <div class="v-chips">{chips}</div>"""


def _row_html(s: IndicatorState) -> str:
    badge = "STALE" if s.stale else s.state.value
    badge_cls = "stale" if s.stale else _STATE_CLASS[s.state]
    manual = '<span class="tag">MANUAL</span>' if s.id in _MANUAL_ROWS else ""
    persist = (
        f' · {s.persisted_periods}p'
        if s.state != State.HEALTHY
        else ""
    )
    counts = '' if s.counts else '<span class="meta warn">· excluded</span>'
    note = f'<div class="note">{_esc(s.note)}</div>' if s.note else ""
    return f"""
      <tr class="row">
        <td class="id">{_esc(s.id)} {manual}</td>
        <td><span class="badge {badge_cls}">{_esc(badge)}</span></td>
        <td class="val">{_value_cell(s)}</td>
        <td class="rule"><span class="mono">{_esc(s.threshold_hit)}</span>{note}</td>
        <td class="asof mono">{_esc(s.as_of)}<br><span class="meta">age {s.staleness_days}d{persist}</span> {counts}</td>
      </tr>"""


def _lvl(label: str, lvl) -> str:
    if not lvl:
        return f'<div class="bcol"><div class="blabel">{_esc(label)}</div><div class="bval mono">—</div></div>'
    d, price = lvl
    return (f'<div class="bcol"><div class="blabel">{_esc(label)}</div>'
            f'<div class="bval mono">${price:,.0f}</div>'
            f'<div class="blabel" style="margin-top:2px">{_esc(d)}</div></div>')


def _channel_panel(ch: TrendChannel | None, sw: SwingLevels | None) -> str:
    out = []

    # Real, level-based support/resistance first — these are the actionable ones.
    if sw is not None:
        out.append('<div class="bounds">')
        out.append(_lvl("Nearest resistance (swing high)", sw.nearest_resistance))
        out.append(_lvl("Nearest support (swing low)", sw.nearest_support))
        out.append(_lvl("All-time high", sw.all_time_high))
        out.append('</div>')
        out.append('<div class="bread"><b>Support/resistance</b> are price pivots — '
                   'levels where price actually turned — not σ-bands.</div>')

    # Secular channel second, clearly flagged as descriptive only.
    if ch is not None:
        rel = "descriptive only" if not ch.reliable else f"±{ch.k:g}σ"
        out.append('<div class="bounds chan">')
        out.append(f'<div class="bcol"><div class="blabel">Secular trend (log-fit)</div>'
                   f'<div class="bval mono">${ch.trend_last:,.0f}</div></div>')
        out.append(f'<div class="bcol"><div class="blabel">Upper band ({rel})</div>'
                   f'<div class="bval mono">${ch.upper_last:,.0f}</div></div>')
        out.append(f'<div class="bcol"><div class="blabel">Lower band ({rel})</div>'
                   f'<div class="bval mono">${ch.lower_last:,.0f}</div></div>')
        out.append(f'<div class="bcol"><div class="blabel">Trend</div>'
                   f'<div class="bval mono">{ch.annualized_trend_pct:+.0f}%/yr</div></div>')
        out.append('</div>')
        out.append(f'<div class="bread">{_esc(ch.read)} '
                   f'<span class="meta">({ch.n} weekly closes, ~{ch.n/ch.periods_per_year:.1f}y)</span></div>')
        if ch.caveat:
            out.append(f'<div class="notice warn" style="margin:0 16px 14px">{_esc(ch.caveat)}</div>')
    return "".join(out)


def render_html(
    cfg: Config,
    assessment: RegimeAssessment,
    states,
    today: date,
    cb_stale: bool,
    bars,
    channel: TrendChannel | None,
    swings: SwingLevels | None = None,
    blocked_until=None,
) -> str:
    label = assessment.label.value
    label_cls = _REGIME_CLASS.get(label, "healthy")
    conf = int(round(assessment.confidence * 100))

    rows = "".join(_row_html(s) for s in states)
    firing = ", ".join(assessment.firing_rows) if assessment.firing_rows else "none"

    chart_svg = render_price_chart(bars, channel, swings, accent=_ACCENT)
    bounds_panel = _channel_panel(channel, swings)

    synthetic = bool(bars) and all((getattr(b, "source", "") == "synthetic") for b in bars)

    notices = []
    if synthetic:
        notices.append(
            '<div class="notice warn">Illustrative data: the price series is a '
            'stylised reconstruction, not live gold prices. Import real history '
            'with <span class="mono">fetch price --file</span> and re-run '
            '<span class="mono">export-web</span> to recompute the chart and analysis.</div>'
        )

    if blocked_until is not None:
        notices.append(
            f'<div class="notice">Weekly cap (§7.3): assessment already ran this week. '
            f'Next recompute {_esc(blocked_until)}. Showing the standing verdict.</div>'
        )
    for s in [s for s in states if s.id in _MANUAL_ROWS and s.stale]:
        notices.append(
            f'<div class="notice warn">Stale manual row: {_esc(s.id)} is '
            f'{s.staleness_days}d old — this verdict carries a warning, not a clean read (§6).</div>'
        )
    for w in assessment.warnings:
        notices.append(f'<div class="notice warn">{_esc(w)}</div>')
    nag = reanchor_nag(cfg, today)
    if nag:
        notices.append(f'<div class="notice warn">Anti-anchoring (§7.6): {_esc(nag)}</div>')
    for n in assessment.notes:
        notices.append(f'<div class="notice">{_esc(n)}</div>')
    notices_html = "\n".join(notices)

    last_close = next((b.close for b in reversed(bars) if b.close is not None), None)
    price_pill = f'<span class="price-pill mono">${last_close:,.0f}</span>' if last_close else ""

    data_json = json.dumps(
        {"assessment": assessment.to_dict(), "generated": today.isoformat()}, indent=2
    )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Gold Regime Tracker — {_esc(today.isoformat())}</title>
<style>
  :root {{
    --bg:#0f1115; --bg2:#0b0d11; --panel:#171a21; --panel2:#1b1f28; --line:#262b36;
    --text:#e6e8ee; --muted:#8b92a1; --faint:#5b6270; --gold:{_ACCENT};
    --healthy:#5fb37a; --transition:#e0ad52; --regime:#d96363; --stale:#6b7180;
  }}
  * {{ box-sizing:border-box; }}
  html {{ -webkit-text-size-adjust:100%; }}
  body {{ margin:0; color:var(--text);
    background:radial-gradient(1200px 600px at 50% -10%, #1a1d25 0%, var(--bg) 55%, var(--bg2) 100%);
    font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif; }}
  .mono {{ font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace; }}
  .wrap {{ max-width:960px; margin:0 auto; padding:30px 22px 64px; }}

  header.top {{ display:flex; align-items:baseline; justify-content:space-between;
    gap:12px; margin-bottom:22px; padding-bottom:16px; border-bottom:1px solid var(--line); }}
  .brand {{ display:flex; align-items:center; gap:10px; }}
  .dot {{ width:10px; height:10px; border-radius:50%; background:var(--gold);
    box-shadow:0 0 0 4px rgba(201,161,74,.14); }}
  .brand h1 {{ font-size:16px; font-weight:650; letter-spacing:.02em; margin:0; }}
  .brand .tagline {{ color:var(--muted); font-size:12px; }}
  .asof-top {{ color:var(--muted); font-size:13px; text-align:right; }}

  .card {{ background:linear-gradient(180deg,var(--panel) 0%,var(--panel2) 100%);
    border:1px solid var(--line); border-radius:14px; box-shadow:0 1px 0 rgba(255,255,255,.02),
    0 12px 30px -18px rgba(0,0,0,.7); }}

  .headline {{ padding:22px 24px; border-left:4px solid var(--muted); margin-bottom:18px; }}
  .headline.healthy {{ border-left-color:var(--healthy); }}
  .headline.transition {{ border-left-color:var(--transition); }}
  .headline.regime {{ border-left-color:var(--regime); }}
  .hl-top {{ display:flex; align-items:center; gap:12px; flex-wrap:wrap; }}
  .regime-label {{ font-size:26px; font-weight:750; letter-spacing:.01em; margin:0; }}
  .healthy .regime-label {{ color:var(--healthy); }}
  .transition .regime-label {{ color:var(--transition); }}
  .regime .regime-label {{ color:var(--regime); }}
  .price-pill {{ margin-left:auto; font-size:15px; font-weight:600; color:var(--gold);
    border:1px solid rgba(201,161,74,.35); background:rgba(201,161,74,.08);
    padding:4px 12px; border-radius:999px; }}
  .sub {{ color:var(--muted); font-size:13px; margin-top:8px; }}
  .conf-bar {{ height:7px; background:var(--line); border-radius:4px; margin:12px 0 4px; overflow:hidden; }}
  .conf-fill {{ height:100%; border-radius:4px; }}
  .healthy .conf-fill {{ background:var(--healthy); }}
  .transition .conf-fill {{ background:var(--transition); }}
  .regime .conf-fill {{ background:var(--regime); }}
  .rec {{ margin-top:15px; padding-top:15px; border-top:1px solid var(--line); font-size:14px; }}
  .rec b {{ color:var(--text); }}

  section {{ margin-top:22px; }}
  section > h2 {{ font-size:11px; text-transform:uppercase; letter-spacing:.08em;
    color:var(--muted); margin:0 0 10px; font-weight:600; }}

  .chart-card {{ padding:18px 18px 8px; }}
  .price-chart {{ width:100%; height:auto; display:block; }}
  .price-chart .grid {{ stroke:var(--line); stroke-width:1; }}
  .price-chart .ylab {{ fill:var(--muted); font:11px ui-monospace,monospace; text-anchor:end; }}
  .price-chart .xlab {{ fill:var(--muted); font:11px ui-monospace,monospace; text-anchor:middle; }}
  .price-chart .band {{ fill:rgba(201,161,74,.08); }}
  .price-chart .bound {{ stroke:rgba(201,161,74,.45); stroke-width:1.2; stroke-dasharray:5 4; }}
  .price-chart .trend {{ stroke:rgba(230,232,238,.45); stroke-width:1.2; stroke-dasharray:2 4; }}
  .price-chart .price {{ fill:none; stroke-width:2; stroke-linejoin:round; stroke-linecap:round; }}
  .price-chart .ref {{ stroke:rgba(139,146,161,.35); stroke-width:1; stroke-dasharray:1 5; }}
  .price-chart .lvl {{ stroke-width:1.2; stroke-dasharray:6 4; }}
  .price-chart .lvl.res {{ stroke:rgba(217,99,99,.6); }}
  .price-chart .lvl.sup {{ stroke:rgba(95,179,122,.6); }}
  .price-chart .lvl.ath {{ stroke:rgba(217,99,99,.35); stroke-dasharray:2 3; }}
  .price-chart .lvllab {{ font:10px ui-monospace,monospace; text-anchor:start; }}
  .price-chart .lvllab.res {{ fill:var(--regime); }}
  .price-chart .lvllab.sup {{ fill:var(--healthy); }}
  .price-chart .lvllab.ath {{ fill:var(--muted); }}
  .price-chart .lvldate {{ fill:var(--muted); }}
  .legend {{ display:flex; gap:16px; flex-wrap:wrap; color:var(--muted); font-size:12px;
    padding:6px 6px 12px; }}
  .legend span {{ display:inline-flex; align-items:center; gap:7px; }}
  .swatch {{ width:16px; height:0; border-top:2px solid; display:inline-block; }}
  .sw-price {{ border-top-color:var(--gold); }}
  .sw-trend {{ border-top:2px dashed rgba(230,232,238,.6); }}
  .sw-band {{ width:16px; height:11px; border:none; background:rgba(201,161,74,.14);
    border-top:1px dashed rgba(201,161,74,.6); border-bottom:1px dashed rgba(201,161,74,.6); }}
  .sw-res {{ border-top-color:rgba(217,99,99,.7); border-top-style:dashed; }}
  .sw-sup {{ border-top-color:rgba(95,179,122,.7); border-top-style:dashed; }}

  .bounds {{ display:grid; grid-template-columns:repeat(4,1fr); gap:1px;
    background:var(--line); border-top:1px solid var(--line); }}
  .bounds:first-child {{ border-top:none; }}
  .bounds.chan {{ }}
  .bcol {{ background:var(--panel2); padding:14px 16px; }}
  .blabel {{ color:var(--muted); font-size:11px; text-transform:uppercase; letter-spacing:.05em; }}
  .bval {{ font-size:20px; font-weight:650; margin-top:4px; }}
  .bread {{ padding:13px 16px; color:var(--text); font-size:13px; background:var(--panel); }}

  table {{ width:100%; border-collapse:collapse; overflow:hidden; }}
  thead th {{ text-align:left; padding:11px 14px; color:var(--muted); font-weight:600;
    text-transform:uppercase; letter-spacing:.06em; font-size:10.5px; }}
  tbody td {{ padding:13px 14px; border-top:1px solid var(--line); vertical-align:top; font-size:13px; }}
  tbody tr:hover td {{ background:rgba(255,255,255,.015); }}
  .id {{ font-weight:650; white-space:nowrap; }}
  .val {{ color:var(--text); }}
  .v-head {{ display:flex; align-items:baseline; gap:9px; flex-wrap:wrap; }}
  .v-primary {{ font-size:19px; font-weight:650; letter-spacing:.01em; }}
  .v-label {{ color:var(--muted); font-size:11px; text-transform:uppercase;
    letter-spacing:.05em; margin-top:1px; }}
  .delta {{ font-size:12px; color:var(--muted); font-variant-numeric:tabular-nums; }}
  .v-chips {{ display:flex; gap:7px; flex-wrap:wrap; margin-top:9px; }}
  .chip {{ display:inline-flex; align-items:baseline; gap:6px; padding:3px 9px;
    border:1px solid var(--line); border-radius:7px; background:rgba(255,255,255,.018); }}
  .chip-k {{ color:var(--muted); font-size:10.5px; text-transform:uppercase; letter-spacing:.04em; }}
  .chip-v {{ font-size:12.5px; color:var(--text); font-weight:550; }}
  .rule, .asof, .meta {{ color:var(--muted); }}
  .badge {{ display:inline-block; padding:3px 10px; border-radius:999px; font-size:10.5px;
    font-weight:700; letter-spacing:.04em; }}
  .badge.healthy {{ background:rgba(95,179,122,.16); color:var(--healthy); }}
  .badge.transition {{ background:rgba(224,173,82,.16); color:var(--transition); }}
  .badge.regime {{ background:rgba(217,99,99,.16); color:var(--regime); }}
  .badge.stale {{ background:rgba(107,113,128,.2); color:var(--stale); }}
  .tag {{ font-size:9.5px; color:var(--muted); border:1px solid var(--line);
    border-radius:5px; padding:1px 6px; margin-left:5px; vertical-align:middle; }}
  .note {{ margin-top:6px; color:var(--text); font-size:12px; opacity:.82; line-height:1.5; }}
  .meta.warn {{ color:var(--regime); }}

  .firing {{ margin:16px 2px; color:var(--muted); font-size:13px; }}
  .firing b {{ color:var(--text); }}
  .notice {{ border:1px solid var(--line); border-left:3px solid var(--muted);
    border-radius:8px; padding:11px 15px; margin:9px 0; font-size:13px;
    color:var(--text); background:var(--panel); }}
  .notice.warn {{ border-left-color:var(--regime); }}
  footer {{ margin-top:30px; color:var(--muted); font-size:12px;
    border-top:1px solid var(--line); padding-top:16px; line-height:1.7; }}
  @media (max-width:620px) {{
    .bounds {{ grid-template-columns:repeat(2,1fr); }}
    .regime-label {{ font-size:22px; }}
    table, thead, tbody, tr, td {{ display:block; }}
    thead {{ display:none; }}
    tbody td {{ border:none; padding:4px 14px; }}
    tbody tr {{ border-top:1px solid var(--line); padding:8px 0; }}
  }}
</style>
</head>
<body>
<div class="wrap">
  <header class="top">
    <div class="brand">
      <span class="dot"></span>
      <div>
        <h1>Gold Regime Tracker</h1>
        <div class="tagline">Structural regime monitor for a physical holder — trend confirmation, not a trading signal.</div>
      </div>
    </div>
    <div class="asof-top">assessment<br><span class="mono">{_esc(today.isoformat())}</span></div>
  </header>

  <div class="card headline {label_cls}">
    <div class="hl-top">
      <div class="regime-label">{_esc(label)}</div>
      {price_pill}
    </div>
    <div class="sub">Macro gate: {_esc(assessment.macro_gate.value)} &nbsp;·&nbsp;
      Confidence {conf}% (fraction of fresh rows agreeing)</div>
    <div class="conf-bar"><div class="conf-fill" style="width:{conf}%"></div></div>
    <div class="rec"><b>Recommendation:</b> {_esc(assessment.recommendation)}</div>
  </div>

  {notices_html}

  <section>
    <h2>Price · secular trend channel · swing support &amp; resistance</h2>
    <div class="card chart-card">
      {chart_svg}
      <div class="legend">
        <span><i class="swatch sw-price"></i> weekly close</span>
        <span><i class="swatch sw-trend"></i> log-trend</span>
        <span><i class="swatch sw-band"></i> ±{(channel.k if channel else 2):g}σ channel</span>
        <span><i class="swatch sw-res"></i> resistance / ATH</span>
        <span><i class="swatch sw-sup"></i> support</span>
      </div>
    </div>
    <div class="card" style="margin-top:14px">{bounds_panel}</div>
  </section>

  <section>
    <h2>Indicator rows</h2>
    <div class="card">
      <table>
        <thead><tr><th>Indicator</th><th>State</th><th>Value</th><th>Rule</th><th>As-of</th></tr></thead>
        <tbody>{rows}</tbody>
      </table>
    </div>
    <div class="firing">Firing (TRANSITION/REGIME, counting): <b>{_esc(firing)}</b></div>
  </section>

  <footer>
    {_esc(EVENT_RISK_DISCLAIMER)}<br>
    The trend channel is a log-price least-squares fit ±{(channel.k if channel else 2):g}σ — a
    descriptive read on the multi-year uptrend, not a forecast and not an
    actionable level. Support/resistance are real price pivots. Static snapshot —
    regenerate weekly with <span class="mono">export-web</span>.
  </footer>

  <script type="application/json" id="assessment-data">{data_json}</script>
</div>
</body>
</html>
"""


def build_site(cfg: Config, out_dir: str, today: date, force: bool = False) -> str:
    """Run an assessment + price analysis and write index.html + assessment.json."""
    assessment, states, cb_stale, blocked = assess(cfg, today, force=force)

    bars = sorted(store.load_price(), key=lambda b: b.date)
    acfg = cfg.get("analysis") or {}
    channel = trend_channel(
        bars,
        k=float(acfg.get("channel_sigma", 2.0)),
        periods_per_year=float(acfg.get("periods_per_year", 52.0)),
    )
    swings = swing_levels(bars, left=int(acfg.get("swing_window", 6)), right=int(acfg.get("swing_window", 6)))

    os.makedirs(out_dir, exist_ok=True)
    page = render_html(cfg, assessment, states, today, cb_stale, bars, channel, swings, blocked_until=blocked)
    index_path = os.path.join(out_dir, "index.html")
    with open(index_path, "w", encoding="utf-8") as fh:
        fh.write(page)
    with open(os.path.join(out_dir, "assessment.json"), "w", encoding="utf-8") as fh:
        json.dump(assessment.to_dict(), fh, indent=2, default=str)
    return index_path
