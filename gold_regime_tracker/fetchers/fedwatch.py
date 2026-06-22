"""FedWatch-style hike/cut odds for the MACRO row (spec §2.5).

CME's FedWatch tool derives meeting probabilities from **30-Day Fed Funds
futures**, which settle to the average daily Fed Funds effective rate over the
contract month. For a contract whose month contains an FOMC decision on day *d*
of *D* days, the implied month-average rate splits into the part of the month at
the pre-meeting rate and the part at the post-meeting rate:

    avg = (d * start_rate + (D - d) * end_rate) / D

so the market-implied post-meeting rate is

    end_rate = (avg * D - d * start_rate) / (D - d)

and the implied probability of a one-step (default 25bp) move is
``(end_rate - start_rate) / step``. This is the standard binary FedWatch model.

The math (``implied_step_odds``) is a pure, unit-tested function. The network
part (pulling CME settlements) is best-effort and supports a ``--file`` import,
exactly like the COT and price fetchers, so a Cloudflare/locked-network wall
never blocks it.
"""

from __future__ import annotations

import calendar
import json
from datetime import date, datetime
from typing import Optional

from .http import HttpError, browser_headers, get

_MONTHS = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}

SETTLEMENTS_URL = (
    "https://www.cmegroup.com/CmeWS/mvc/Settlements/Futures/Settlements/"
    "{product}/FUT?strategy=DEFAULT&tradeDate="
)


class FetchError(RuntimeError):
    pass


# --- pure methodology ---------------------------------------------------------


def implied_step_odds(
    month_avg_rate: float,
    days_in_month: int,
    meeting_day: int,
    start_rate: float,
    step_bp: float = 25.0,
) -> dict:
    """Return implied next-meeting odds from one contract's month-average rate.

    ``hike_odds_pct`` is the probability of a +step move (0 if the implied move
    is a cut); ``cut_odds_pct`` the mirror. Both are clamped to [0, 100].
    """
    n_after = days_in_month - meeting_day
    if n_after <= 0 or meeting_day <= 0:
        raise FetchError("Meeting day must fall strictly inside the contract month.")
    end_rate = (month_avg_rate * days_in_month - meeting_day * start_rate) / n_after
    change = end_rate - start_rate
    step = step_bp / 100.0
    prob = change / step if step else 0.0
    hike = max(0.0, min(100.0, prob * 100.0))
    cut = max(0.0, min(100.0, -prob * 100.0))
    return {
        "hike_odds_pct": round(hike, 1),
        "cut_odds_pct": round(cut, 1),
        "implied_change_bp": round(change * 100, 1),
        "implied_end_rate": round(end_rate, 3),
    }


def _as_date(m) -> date:
    if isinstance(m, date):
        return m
    return datetime.strptime(str(m), "%Y-%m-%d").date()


def next_meeting(today: date, meetings: list) -> Optional[date]:
    dates = sorted(_as_date(m) for m in meetings)
    for d in dates:
        if d >= today:
            return d
    return None


# --- settlement parsing / fetch ----------------------------------------------


def parse_settlements(data) -> dict:
    """Map {(year, month): month_avg_rate} from a CME settlements JSON blob.

    Accepts the raw dict (with a ``settlements`` list of ``{month, settle}``) or
    an already-extracted list. ``month`` looks like ``"JUL 26"``; the implied
    average rate is ``100 - settle``.
    """
    rows = data.get("settlements", data) if isinstance(data, dict) else data
    out: dict[tuple[int, int], float] = {}
    for r in rows:
        label = (r.get("month") or "").strip().upper()
        settle = str(r.get("settle", "")).replace(",", "").strip()
        if not label or settle in ("", "-"):
            continue
        parts = label.split()
        if len(parts) != 2 or parts[0] not in _MONTHS:
            continue
        month = _MONTHS[parts[0]]
        yy = int(parts[1])
        year = 2000 + yy if yy < 100 else yy
        try:
            out[(year, month)] = 100.0 - float(settle)
        except ValueError:
            continue
    return out


def fetch_settlements(cfg) -> dict:
    product = (cfg.get("macro_fetch") or {}).get("cme_product", 305)
    url = SETTLEMENTS_URL.format(product=product)
    try:
        raw = get(url, headers=browser_headers({"Accept": "application/json,*/*"}))
    except HttpError as exc:
        raise FetchError(f"CME settlements fetch failed: {exc}") from exc
    try:
        return parse_settlements(json.loads(raw.decode("utf-8", errors="replace")))
    except (ValueError, TypeError) as exc:
        raise FetchError(f"Could not parse CME settlements JSON: {exc}") from exc


def from_file(path: str) -> dict:
    """Import a saved CME settlements JSON file (browser-downloaded)."""
    with open(path, "r", encoding="utf-8") as fh:
        return parse_settlements(json.load(fh))


# --- top-level compute --------------------------------------------------------


def _next_month(year: int, month: int) -> tuple[int, int]:
    return (year + 1, 1) if month == 12 else (year, month + 1)


def compute(cfg, today: date, settlements: dict) -> Optional[dict]:
    """Compute next-meeting hike odds. Returns a result dict, or None if the next
    meeting and its contracts are unavailable.

    Uses the meeting-month contract to back out the post-meeting rate when the
    meeting is early enough in the month for that to be stable; otherwise (a
    late-month meeting, tiny post-meeting window) it uses the *next* month's
    contract average as the post-meeting rate directly — the standard FedWatch
    treatment, since a tiny denominator otherwise amplifies noise wildly.
    """
    mf = cfg.get("macro_fetch") or {}
    meeting = next_meeting(today, mf.get("fomc_meetings") or [])
    if meeting is None:
        return None

    start = float(mf.get("current_target_midpoint", 0.0))
    step = float(mf.get("step_bp", 25)) / 100.0
    D = calendar.monthrange(meeting.year, meeting.month)[1]
    n_after = D - meeting.day
    min_after = int(mf.get("min_after_days", 7))

    avg_m = settlements.get((meeting.year, meeting.month))
    avg_next = settlements.get(_next_month(meeting.year, meeting.month))

    if n_after >= min_after and avg_m is not None:
        end_rate = (avg_m * D - meeting.day * start) / n_after
        method = "meeting-month back-out"
    elif avg_next is not None:
        end_rate = avg_next
        method = "next-month contract"
    elif avg_m is not None and n_after > 0:
        end_rate = (avg_m * D - meeting.day * start) / n_after
        method = "meeting-month back-out (no next contract)"
    else:
        return None

    change = end_rate - start
    prob = change / step if step else 0.0
    return {
        "meeting": meeting.isoformat(),
        "method": method,
        "hike_odds_pct": round(max(0.0, min(100.0, prob * 100.0)), 1),
        "cut_odds_pct": round(max(0.0, min(100.0, -prob * 100.0)), 1),
        "implied_change_bp": round(change * 100, 1),
        "implied_end_rate": round(end_rate, 3),
    }
