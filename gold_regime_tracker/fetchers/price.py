"""Price + moving-average fetcher — PRICE row (spec §2.2).

Pulls raw daily OHLC (default: Stooq XAU/USD) and computes 21/50/100/200-day
SMAs, the weekly close, and distance-to-200DMA. Raw price only — no forecast
scraping (§2.2). Pick one series and be consistent.
"""

from __future__ import annotations

import csv
import io
import urllib.request
from datetime import date, datetime
from typing import Optional

from ..models import PriceBar

STOOQ_URL = "https://stooq.com/q/d/l/?s={symbol}&i=d"
DEFAULT_SYMBOL = "xauusd"


class FetchError(RuntimeError):
    pass


def _download(symbol: str, timeout: int = 30) -> str:
    url = STOOQ_URL.format(symbol=symbol)
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as exc:
        raise FetchError(f"Price download failed for {symbol}: {exc}") from exc


def _sma(closes: list[float], window: int) -> Optional[float]:
    if len(closes) < window:
        return None
    return round(sum(closes[-window:]) / window, 2)


def build_bars(rows: list[tuple[str, float]]) -> list[PriceBar]:
    """rows: list of (date, close) ascending. Computes SMAs cumulatively."""
    rows = sorted(rows, key=lambda r: r[0])
    closes: list[float] = []
    bars: list[PriceBar] = []
    for d, close in rows:
        closes.append(close)
        sma200 = _sma(closes, 200)
        dist = round((close - sma200) / sma200 * 100, 2) if sma200 else None
        bars.append(
            PriceBar(
                date=d,
                close=close,
                sma21=_sma(closes, 21),
                sma50=_sma(closes, 50),
                sma100=_sma(closes, 100),
                sma200=sma200,
                dist_200dma_pct=dist,
            )
        )
    return bars


def parse_stooq(text: str) -> list[PriceBar]:
    reader = csv.DictReader(io.StringIO(text))
    rows: list[tuple[str, float]] = []
    for r in reader:
        d = (r.get("Date") or "").strip()
        c = (r.get("Close") or "").strip()
        if not d or not c:
            continue
        try:
            rows.append((d, float(c)))
        except ValueError:
            continue
    if not rows:
        raise FetchError("No usable rows in price CSV (rate-limited or empty?).")
    return build_bars(rows)


def fetch(symbol: str = DEFAULT_SYMBOL) -> list[PriceBar]:
    return parse_stooq(_download(symbol))


def latest_weekly_close(symbol: str = DEFAULT_SYMBOL) -> Optional[PriceBar]:
    """Most recent Friday (or last available) bar — the weekly close (§4)."""
    bars = fetch(symbol)
    if not bars:
        return None
    fridays = [b for b in bars if datetime.strptime(b.date, "%Y-%m-%d").weekday() == 4]
    return (fridays or bars)[-1]
