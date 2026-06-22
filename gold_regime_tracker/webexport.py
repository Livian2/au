"""Static-site exporter (spec §6) for Cloudflare Pages / any static host.

Renders the weekly assessment to a single self-contained ``index.html`` (data
embedded inline — no fetch, no API, works over file:// too) plus a sidecar
``assessment.json`` for archiving. Deliberately plain: no flashing, no
auto-refresh, no push — a page you visit on a schedule, not one that pings you.
"""

from __future__ import annotations

import html
import json
import os
from datetime import date

from .config import Config
from .engine import assess
from .guardrails import EVENT_RISK_DISCLAIMER, reanchor_nag
from .models import IndicatorState, RegimeAssessment, State

_MANUAL_ROWS = {"CB_BID"}

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


def _row_html(s: IndicatorState) -> str:
    badge = "STALE" if s.stale else s.state.value
    badge_cls = "stale" if s.stale else _STATE_CLASS[s.state]
    manual = '<span class="tag">MANUAL</span>' if s.id in _MANUAL_ROWS else ""
    persist = (
        f'<span class="meta">persisted {s.persisted_periods}p</span>'
        if s.state != State.HEALTHY
        else ""
    )
    counts = '' if s.counts else '<span class="meta warn">does not count</span>'
    note = f'<div class="note">{_esc(s.note)}</div>' if s.note else ""
    return f"""
      <tr class="row {badge_cls}">
        <td class="id">{_esc(s.id)} {manual}</td>
        <td><span class="badge {badge_cls}">{_esc(badge)}</span></td>
        <td class="val">{_esc(s.value)}</td>
        <td class="rule">{_esc(s.threshold_hit)}{note}</td>
        <td class="asof">{_esc(s.as_of)}<br><span class="meta">age {s.staleness_days}d</span> {persist} {counts}</td>
      </tr>"""


def render_html(
    cfg: Config,
    assessment: RegimeAssessment,
    states,
    today: date,
    cb_stale: bool,
    blocked_until=None,
) -> str:
    label = assessment.label.value
    label_cls = _REGIME_CLASS.get(label, "healthy")
    conf = int(round(assessment.confidence * 100))

    rows = "".join(_row_html(s) for s in states)
    firing = ", ".join(assessment.firing_rows) if assessment.firing_rows else "none"

    notices = []
    if blocked_until is not None:
        notices.append(
            f'<div class="notice">Weekly cap (§7.3): assessment already ran this week. '
            f'Next recompute {_esc(blocked_until)}. Showing the standing verdict.</div>'
        )
    overdue_manual = [s for s in states if s.id in _MANUAL_ROWS and s.stale]
    for s in overdue_manual:
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

    data_json = json.dumps(
        {
            "assessment": assessment.to_dict(),
            "generated": today.isoformat(),
        },
        indent=2,
    )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Gold Regime Tracker — {_esc(today.isoformat())}</title>
<style>
  :root {{
    --bg:#15171c; --panel:#1d2027; --line:#2c303a; --text:#d7dae0; --muted:#878d99;
    --healthy:#5fb37a; --transition:#d8a24a; --regime:#cf5b5b; --stale:#6b7180;
  }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--text);
    font:15px/1.5 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace; }}
  .wrap {{ max-width:920px; margin:0 auto; padding:28px 20px 60px; }}
  h1 {{ font-size:15px; font-weight:600; letter-spacing:.04em; color:var(--muted);
    text-transform:uppercase; margin:0 0 18px; }}
  .headline {{ background:var(--panel); border:1px solid var(--line); border-left-width:4px;
    border-radius:8px; padding:20px 22px; margin-bottom:16px; }}
  .headline.healthy {{ border-left-color:var(--healthy); }}
  .headline.transition {{ border-left-color:var(--transition); }}
  .headline.regime {{ border-left-color:var(--regime); }}
  .regime-label {{ font-size:24px; font-weight:700; margin:0 0 6px; }}
  .healthy .regime-label {{ color:var(--healthy); }}
  .transition .regime-label {{ color:var(--transition); }}
  .regime .regime-label {{ color:var(--regime); }}
  .sub {{ color:var(--muted); font-size:13px; }}
  .rec {{ margin-top:14px; padding-top:14px; border-top:1px solid var(--line); }}
  .conf-bar {{ height:6px; background:var(--line); border-radius:3px; margin:10px 0 4px; overflow:hidden; }}
  .conf-fill {{ height:100%; }}
  .healthy .conf-fill {{ background:var(--healthy); }}
  .transition .conf-fill {{ background:var(--transition); }}
  .regime .conf-fill {{ background:var(--regime); }}
  table {{ width:100%; border-collapse:collapse; background:var(--panel);
    border:1px solid var(--line); border-radius:8px; overflow:hidden; }}
  th, td {{ text-align:left; padding:10px 12px; border-top:1px solid var(--line);
    vertical-align:top; font-size:13px; }}
  th {{ color:var(--muted); font-weight:600; text-transform:uppercase;
    letter-spacing:.04em; font-size:11px; border-top:none; }}
  .id {{ font-weight:600; white-space:nowrap; }}
  .val {{ color:var(--text); }}
  .rule, .asof, .meta {{ color:var(--muted); }}
  .badge {{ display:inline-block; padding:2px 8px; border-radius:11px; font-size:11px;
    font-weight:700; letter-spacing:.03em; }}
  .badge.healthy {{ background:rgba(95,179,122,.15); color:var(--healthy); }}
  .badge.transition {{ background:rgba(216,162,74,.15); color:var(--transition); }}
  .badge.regime {{ background:rgba(207,91,91,.15); color:var(--regime); }}
  .badge.stale {{ background:rgba(107,113,128,.18); color:var(--stale); }}
  .tag {{ font-size:10px; color:var(--muted); border:1px solid var(--line);
    border-radius:4px; padding:1px 5px; margin-left:4px; }}
  .note {{ margin-top:5px; color:var(--text); font-size:12px; opacity:.85; }}
  .meta.warn {{ color:var(--regime); }}
  .firing {{ margin:16px 0; color:var(--muted); font-size:13px; }}
  .firing b {{ color:var(--text); }}
  .notice {{ background:var(--panel); border:1px solid var(--line);
    border-left:3px solid var(--muted); border-radius:6px; padding:10px 14px;
    margin:8px 0; font-size:13px; color:var(--text); }}
  .notice.warn {{ border-left-color:var(--regime); }}
  footer {{ margin-top:26px; color:var(--muted); font-size:12px;
    border-top:1px solid var(--line); padding-top:14px; }}
  section {{ margin-top:22px; }}
  section > h2 {{ font-size:11px; text-transform:uppercase; letter-spacing:.05em;
    color:var(--muted); margin:0 0 8px; }}
</style>
</head>
<body>
<div class="wrap">
  <h1>Gold Regime Tracker &middot; assessment for {_esc(today.isoformat())}</h1>

  <div class="headline {label_cls}">
    <div class="regime-label">{_esc(label)}</div>
    <div class="sub">Macro gate: {_esc(assessment.macro_gate.value)} &nbsp;|&nbsp;
      Confidence {conf}% (fraction of fresh rows agreeing)</div>
    <div class="conf-bar"><div class="conf-fill" style="width:{conf}%"></div></div>
    <div class="rec"><b>Recommendation:</b> {_esc(assessment.recommendation)}</div>
  </div>

  {notices_html}

  <section>
    <h2>Rows</h2>
    <table>
      <thead><tr><th>Indicator</th><th>State</th><th>Value</th><th>Rule</th><th>As-of</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
  </section>

  <div class="firing">Firing (TRANSITION/REGIME, counting): <b>{_esc(firing)}</b></div>

  <footer>
    {_esc(EVENT_RISK_DISCLAIMER)}<br>
    This is a static snapshot — it does not auto-refresh. Regenerate on your
    weekly schedule with <code>export-web</code>.
  </footer>

  <script type="application/json" id="assessment-data">{data_json}</script>
</div>
</body>
</html>
"""


def build_site(cfg: Config, out_dir: str, today: date, force: bool = False) -> str:
    """Run an assessment and write index.html + assessment.json into out_dir.
    Returns the path to the written index.html."""
    assessment, states, cb_stale, blocked = assess(cfg, today, force=force)
    os.makedirs(out_dir, exist_ok=True)
    page = render_html(cfg, assessment, states, today, cb_stale, blocked_until=blocked)
    index_path = os.path.join(out_dir, "index.html")
    with open(index_path, "w", encoding="utf-8") as fh:
        fh.write(page)
    with open(os.path.join(out_dir, "assessment.json"), "w", encoding="utf-8") as fh:
        json.dump(assessment.to_dict(), fh, indent=2, default=str)
    return index_path
