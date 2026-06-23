"""Validate every parser against fixtures that mirror the REAL upstream schemas.

These are the formats the live fetchers will actually see — CFTC's
Disaggregated COT text, a Stooq OHLC CSV, the CME settlements JSON (with its
"Total" row and "-" placeholders), and a WGC export that carries regional
*and* total columns. The live HTTP can't be exercised from a sandbox, so this
is the next best thing: prove the parsing handles the real shapes and quirks.
"""

import json
import os
from datetime import date

from gold_regime_tracker.config import load_config
from gold_regime_tracker.fetchers import cftc, fedwatch, price, wgc

FIX = os.path.join(os.path.dirname(__file__), "fixtures")
CFG = load_config()


def _read(name):
    with open(os.path.join(FIX, name), "r", encoding="utf-8") as fh:
        return fh.read()


def test_cftc_disagg_real_headers():
    recs = cftc.parse_text(_read("cftc_disagg_sample.txt"))
    # Only the two gold (088691) rows, silver dropped; sorted ascending.
    assert [r.report_date for r in recs] == ["2026-06-09", "2026-06-16"]
    latest = recs[-1]
    assert latest.mm_long == 92000 and latest.mm_short == 38000
    assert latest.mm_net == 54000
    assert latest.open_interest == 501234


def test_stooq_real_csv():
    bars = price.parse_stooq(_read("stooq_sample.csv"), source="file")
    assert bars[-1].date == "2026-06-19"
    assert bars[-1].close == 4144.00
    assert bars[-1].source == "file"


def test_cme_settlements_real_json():
    data = json.loads(_read("cme_settlements_sample.json"))
    settl = fedwatch.parse_settlements(data)
    # "Total" row and "-" settle skipped; months parsed; rate = 100 - settle.
    assert (2026, 7) in settl and (2026, 8) in settl
    assert abs(settl[(2026, 8)] - 5.35) < 1e-9
    res = fedwatch.compute(CFG, date(2026, 6, 22), settl)
    assert res["meeting"] == "2026-07-29"
    assert res["method"] == "next-month contract"   # late-month meeting uses AUG


def test_wgc_picks_total_not_regional_columns():
    recs = wgc.parse_csv(_read("wgc_etf_sample.csv"), CFG)
    # Must pick "Total (tonnes)" (4080), not "North America (tonnes)" (1900).
    assert recs[0].tonnes == 4080.0
    assert recs[-1].tonnes == 3980.0
    assert recs[-1].net_flow_usd == -2.0e9          # Total flows, not a region
    assert recs[-1].aum_usd == 272000000000
    assert recs[-1].ytd_flow_usd == -4.5e9          # Mar+Apr+May 2026
