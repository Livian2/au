"""Persistence (spec §6, §7). Plain JSON files — no database needed for a tool
you visit weekly.

Two stores, deliberately separated so an ephemeral CI runner does the right
thing:

* ``data/`` — **auto cache** (COT, price). Re-fetched every run; gitignored.
* ``journal/`` — **tracked** manual entries (CB_BID, ETF, MACRO) and the
  assessment ``history`` log. These are deliberate human decisions plus the
  audit trail that the 90-day minimum-decision-interval guardrail (§7.1) reads,
  so they belong in version control and must survive across runs.

Both roots are overridable via ``GRT_DATA_DIR`` / ``GRT_JOURNAL_DIR`` (used to
isolate the synthetic demo from the real tracked journal).
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from typing import Optional

from .models import (
    CbRecord,
    CotRecord,
    EtfRecord,
    MacroRecord,
    PriceBar,
    RegimeAssessment,
)

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _data_dir() -> str:
    return os.environ.get("GRT_DATA_DIR", os.path.join(_REPO, "data"))


def _journal_dir() -> str:
    return os.environ.get("GRT_JOURNAL_DIR", os.path.join(_REPO, "journal"))


# name -> (filename, is_journal)
FILES = {
    "cot": ("cot.json", False),
    "price": ("price.json", False),
    "etf": ("etf.json", True),
    "cb": ("cb.json", True),
    "macro": ("macro.json", True),
    "history": ("history.json", True),
}


def _path(name: str) -> str:
    fname, journal = FILES[name]
    root = _journal_dir() if journal else _data_dir()
    os.makedirs(root, exist_ok=True)
    return os.path.join(root, fname)


def _read(name: str) -> list:
    p = _path(name)
    if not os.path.exists(p):
        return []
    with open(p, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _write(name: str, rows: list) -> None:
    with open(_path(name), "w", encoding="utf-8") as fh:
        json.dump(rows, fh, indent=2, default=str)


# --- typed loaders ------------------------------------------------------------


def load_cot() -> list[CotRecord]:
    return [CotRecord(**r) for r in _read("cot")]


def load_price() -> list[PriceBar]:
    return [PriceBar(**r) for r in _read("price")]


def load_etf() -> list[EtfRecord]:
    return [EtfRecord(**r) for r in _read("etf")]


def load_cb() -> list[CbRecord]:
    return [CbRecord(**r) for r in _read("cb")]


def load_macro() -> list[MacroRecord]:
    return [MacroRecord(**r) for r in _read("macro")]


def load_history() -> list[dict]:
    return _read("history")


# --- upserts (keyed on the natural period key) --------------------------------


def _upsert(name: str, record, key: str) -> None:
    rows = _read(name)
    d = asdict(record)
    rows = [r for r in rows if r.get(key) != d.get(key)]
    rows.append(d)
    rows.sort(key=lambda r: str(r.get(key)))
    _write(name, rows)


def save_cot(rec: CotRecord) -> None:
    _upsert("cot", rec, "report_date")


def save_price(bar: PriceBar) -> None:
    _upsert("price", bar, "date")


def save_etf(rec: EtfRecord) -> None:
    _upsert("etf", rec, "month")


def save_cb(rec: CbRecord) -> None:
    _upsert("cb", rec, "quarter")


def save_macro(rec: MacroRecord) -> None:
    _upsert("macro", rec, "date")


def append_history(assessment: RegimeAssessment) -> None:
    rows = _read("history")
    rows.append(assessment.to_dict())
    rows.sort(key=lambda r: str(r.get("date")))
    _write("history", rows)


def latest(records: list, key) -> Optional[object]:
    if not records:
        return None
    return sorted(records, key=key)[-1]
