"""WGC gold-backed ETF holdings & flows importer for the ETF_HOLD row (§2.3).

The World Gold Council's "Global gold-backed ETF holdings and flows" dataset has
no clean public API — you download the file from Goldhub. So this is primarily a
tolerant CSV importer (export the WGC sheet to CSV), with an optional configured
URL for a best-effort fetch. Stdlib only: CSV, not XLSX — save the sheet as CSV.

The parser maps columns by fuzzy header match (overridable in config), reads the
monthly series, and computes per-month YTD cumulative flow so the consecutive-
outflow and persistence logic have real history.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime
from typing import Optional

from ..models import EtfRecord
from .http import HttpError, browser_headers, get


class FetchError(RuntimeError):
    pass


# Priority-ordered match phrases per field. Earlier phrases win, so the "Total"
# column beats a regional "North America (tonnes)" column when both exist.
_PRIORITY = {
    "month": ["date", "month", "period"],
    "tonnes": ["total (tonnes)", "total tonnes", "total holdings", "total", "tonne", "holdings"],
    "flow": ["total flows", "total flow", "total net flow", "total (us$)", "net flow", "fund flow", "flow"],
    "aum": ["total aum", "total assets", "assets under", "aum", "value", "assets"],
}


def _pick_columns(headers: list[str], overrides: dict) -> dict:
    cols: dict[str, Optional[str]] = {"month": None, "tonnes": None, "flow": None, "aum": None}
    pairs = [(h, h.lower().strip()) for h in headers]
    used: set[str] = set()
    for key in cols:
        ov = overrides.get(key)
        if ov and ov in headers:
            cols[key] = ov
            used.add(ov)
            continue
        for phrase in _PRIORITY[key]:
            match = next((orig for orig, low in pairs if phrase in low and orig not in used), None)
            if match:
                cols[key] = match
                used.add(match)
                break
    if not cols["month"] or not cols["tonnes"]:
        raise FetchError(
            "Could not locate the month and tonnes columns. Set "
            "etf_fetch.columns.{month,tonnes,flow,aum} in config to the exact headers."
        )
    return cols


def _to_month(value: str) -> Optional[str]:
    v = (value or "").strip()
    if not v:
        return None
    for fmt in ("%Y-%m", "%Y-%m-%d", "%b %Y", "%B %Y", "%m/%d/%Y", "%d/%m/%Y", "%Y/%m"):
        try:
            return datetime.strptime(v, fmt).strftime("%Y-%m")
        except ValueError:
            continue
    # Last resort: a leading YYYY-MM substring.
    if len(v) >= 7 and v[4] in "-/":
        return v[:7].replace("/", "-")
    return None


def _num(value: str, scale: float) -> Optional[float]:
    s = (value or "").strip().replace(",", "").replace("$", "")
    if s in ("", "-", "n/a", "N/A"):
        return None
    try:
        return float(s) * scale
    except ValueError:
        return None


def parse_csv(text: str, cfg=None) -> list[EtfRecord]:
    ef = (cfg.get("etf_fetch") if cfg else None) or {}
    overrides = ef.get("columns") or {}
    tonnes_scale = float(ef.get("tonnes_scale", 1))
    flow_scale = float(ef.get("flow_scale", 1))
    aum_scale = float(ef.get("aum_scale", 1))

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise FetchError("Empty ETF CSV.")
    cols = _pick_columns(list(reader.fieldnames), overrides)

    rows: list[tuple[str, float, Optional[float], Optional[float]]] = []
    for r in reader:
        month = _to_month(r.get(cols["month"], ""))
        tonnes = _num(r.get(cols["tonnes"], ""), tonnes_scale)
        if month is None or tonnes is None:
            continue
        flow = _num(r.get(cols["flow"], ""), flow_scale) if cols["flow"] else None
        aum = _num(r.get(cols["aum"], ""), aum_scale) if cols["aum"] else None
        rows.append((month, tonnes, flow, aum))

    if not rows:
        raise FetchError("No usable ETF rows parsed (check the column mapping).")
    rows.sort(key=lambda x: x[0])

    # Per-month YTD cumulative flow (resets each calendar year).
    out: list[EtfRecord] = []
    ytd = 0.0
    cur_year = None
    for month, tonnes, flow, aum in rows:
        year = month[:4]
        if year != cur_year:
            cur_year, ytd = year, 0.0
        if flow is not None:
            ytd += flow
        out.append(
            EtfRecord(
                month=month,
                tonnes=round(tonnes, 1),
                aum_usd=aum,
                net_flow_usd=flow,
                ytd_flow_usd=(round(ytd, 2) if flow is not None else None),
                source_tag="semi-auto",
            )
        )
    return out


def from_file(path: str, cfg=None) -> list[EtfRecord]:
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        return parse_csv(fh.read(), cfg)


def fetch(cfg) -> list[EtfRecord]:
    url = (cfg.get("etf_fetch") or {}).get("source_url") or ""
    if not url:
        raise FetchError(
            "No etf_fetch.source_url configured. Download the WGC 'Global "
            "gold-backed ETF holdings and flows' file, save it as CSV, and import "
            "with: fetch etf --file <path>."
        )
    try:
        text = get(url, headers=browser_headers({"Accept": "text/csv,*/*"})).decode("utf-8", errors="replace")
    except HttpError as exc:
        raise FetchError(f"ETF download failed: {exc}") from exc
    return parse_csv(text, cfg)
