"""Persistence: raw records, manual journal entries, and the assessment history
log (spec §6, §7). Plain JSON files under ``data/`` — no database needed for a
tool you visit weekly.
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

DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data"
)

FILES = {
    "cot": "cot.json",
    "price": "price.json",
    "etf": "etf.json",
    "cb": "cb.json",
    "macro": "macro.json",
    "history": "history.json",
}


def _path(name: str) -> str:
    os.makedirs(DATA_DIR, exist_ok=True)
    return os.path.join(DATA_DIR, FILES[name])


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
