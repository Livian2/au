"""Tests for the WGC ETF CSV importer."""

import pytest

from gold_regime_tracker.config import load_config
from gold_regime_tracker.fetchers import wgc

CFG = load_config()

SAMPLE = """Date,Total (tonnes),Total flows (US$),Total AUM (US$)
2025-11,4150,1000000000,300000000000
2025-12,4135,-500000000,295000000000
2026-01,4120,-800000000,290000000000
2026-02,4100,-1200000000,285000000000
"""


def test_parse_maps_aliased_headers_and_sorts():
    recs = wgc.parse_csv(SAMPLE, CFG)
    assert [r.month for r in recs] == ["2025-11", "2025-12", "2026-01", "2026-02"]
    assert recs[0].tonnes == 4150
    assert recs[-1].net_flow_usd == -1.2e9


def test_ytd_resets_each_calendar_year():
    recs = wgc.parse_csv(SAMPLE, CFG)
    by_month = {r.month: r for r in recs}
    # Dec 2025 YTD = Nov + Dec (only the two 2025 rows in the sample).
    assert by_month["2025-12"].ytd_flow_usd == pytest.approx(0.5e9)
    # Feb 2026 YTD = Jan + Feb (2026 resets at the year boundary).
    assert by_month["2026-02"].ytd_flow_usd == pytest.approx(-2.0e9)


def test_flow_scale_applies():
    cfg = load_config()
    cfg._d["etf_fetch"]["flow_scale"] = 1000000  # file expressed in USD millions
    csv_millions = "month,tonnes,flow\n2026-01,4000,-1200\n"
    recs = wgc.parse_csv(csv_millions, cfg)
    assert recs[0].net_flow_usd == -1.2e9


def test_missing_required_columns_raises():
    with pytest.raises(wgc.FetchError):
        wgc.parse_csv("foo,bar\n1,2\n", CFG)


def test_classifies_into_transition_band():
    # Sanity: the imported tail (4100t, ytd<0) flows through the classifier.
    from datetime import date
    from gold_regime_tracker.classify import classify_etf

    recs = wgc.parse_csv(SAMPLE, CFG)
    state = classify_etf(CFG, recs[-1], recs[:-1], date(2026, 2, 20))
    assert state.id == "ETF_HOLD"
