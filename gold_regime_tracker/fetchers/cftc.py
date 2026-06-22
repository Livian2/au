"""CFTC Commitments of Traders fetcher — MM_NET, MM_SHORT (spec §2.1).

Source : CFTC Disaggregated Futures-Only report.
Contract: COMEX Gold, 100 troy oz, CFTC code 088691.
Release : Fridays 15:30 ET, reflecting the prior Tuesday close (3-day lag).

We pull the annual bulk text file (zip) and filter for the gold contract. This
is Phase 1, highest-value/lowest-effort (§8).
"""

from __future__ import annotations

import csv
import io
import urllib.request
import zipfile
from datetime import date, datetime
from typing import Optional

from ..models import CotRecord

GOLD_CODE = "088691"
ANNUAL_URL = "https://www.cftc.gov/files/dea/history/fut_disagg_txt_{year}.zip"

# Disaggregated report column names (CFTC headers are stable).
COL_CODE = "CFTC_Contract_Market_Code"
COL_DATE = "Report_Date_as_YYYY-MM-DD"
COL_OI = "Open_Interest_All"
COL_LONG = "M_Money_Positions_Long_All"
COL_SHORT = "M_Money_Positions_Short_All"
COL_SPREAD = "M_Money_Positions_Spread_All"


class FetchError(RuntimeError):
    pass


def _download(year: int, timeout: int = 30) -> bytes:
    url = ANNUAL_URL.format(year=year)
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.read()
    except Exception as exc:  # network unavailable, 404, etc.
        raise FetchError(f"CFTC download failed for {year}: {exc}") from exc


def _parse_int(value: str) -> int:
    value = (value or "").strip().replace(",", "")
    if value in ("", "."):
        return 0
    return int(float(value))


def parse_zip(blob: bytes) -> list[CotRecord]:
    """Extract every COMEX gold managed-money row from an annual zip blob."""
    out: list[CotRecord] = []
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        name = next((n for n in zf.namelist() if n.lower().endswith(".txt")), None)
        if name is None:
            raise FetchError("No .txt member in CFTC annual zip.")
        text = zf.read(name).decode("utf-8", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    for row in reader:
        code = (row.get(COL_CODE) or "").strip()
        if code != GOLD_CODE:
            continue
        long_ = _parse_int(row.get(COL_LONG, ""))
        short_ = _parse_int(row.get(COL_SHORT, ""))
        rpt = (row.get(COL_DATE) or "").strip()
        out.append(
            CotRecord(
                report_date=rpt,
                fetch_date=date.today().isoformat(),
                mm_long=long_,
                mm_short=short_,
                mm_net=long_ - short_,
                mm_spread=_parse_int(row.get(COL_SPREAD, "")),
                open_interest=_parse_int(row.get(COL_OI, "")),
            )
        )
    out.sort(key=lambda r: r.report_date)
    return out


def fetch_year(year: Optional[int] = None) -> list[CotRecord]:
    """Fetch and parse all gold COT rows for a year (default: current year)."""
    year = year or date.today().year
    return parse_zip(_download(year))


def latest_record(year: Optional[int] = None) -> Optional[CotRecord]:
    records = fetch_year(year)
    return records[-1] if records else None
