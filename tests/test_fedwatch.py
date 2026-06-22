"""Tests for the FedWatch implied-odds math and settlement parsing."""

from datetime import date

import pytest

from gold_regime_tracker.config import load_config
from gold_regime_tracker.fetchers import fedwatch

CFG = load_config()


def test_full_hike_is_100pct():
    # 30-day month, meeting mid-month, a clean +25bp move => avg sits halfway.
    avg = (15 * 5.0 + 15 * 5.25) / 30  # = 5.125
    o = fedwatch.implied_step_odds(avg, 30, 15, start_rate=5.0, step_bp=25)
    assert o["hike_odds_pct"] == 100.0
    assert o["implied_end_rate"] == 5.25
    assert o["implied_change_bp"] == 25.0


def test_half_hike_is_50pct():
    avg = (15 * 5.0 + 15 * 5.125) / 30
    o = fedwatch.implied_step_odds(avg, 30, 15, start_rate=5.0, step_bp=25)
    assert o["hike_odds_pct"] == 50.0
    assert o["cut_odds_pct"] == 0.0


def test_cut_shows_zero_hike_and_positive_cut():
    avg = (15 * 5.0 + 15 * 4.75) / 30
    o = fedwatch.implied_step_odds(avg, 30, 15, start_rate=5.0, step_bp=25)
    assert o["hike_odds_pct"] == 0.0
    assert o["cut_odds_pct"] == 100.0


def test_meeting_must_be_inside_month():
    with pytest.raises(fedwatch.FetchError):
        fedwatch.implied_step_odds(5.0, 30, 30, start_rate=5.0)


def test_next_meeting_picks_first_future_date():
    meetings = ["2026-03-18", "2026-06-17", "2026-07-29"]
    assert fedwatch.next_meeting(date(2026, 6, 22), meetings) == date(2026, 7, 29)
    assert fedwatch.next_meeting(date(2026, 6, 17), meetings) == date(2026, 6, 17)
    assert fedwatch.next_meeting(date(2027, 1, 1), meetings) is None


def test_parse_settlements_reads_month_and_skips_blanks():
    data = {"settlements": [
        {"month": "JUL 26", "settle": "94.875"},
        {"month": "AUG 26", "settle": "-"},
        {"month": "garbage", "settle": "1.0"},
    ]}
    out = fedwatch.parse_settlements(data)
    assert out[(2026, 7)] == pytest.approx(5.125)
    assert (2026, 8) not in out


def test_compute_late_month_meeting_uses_next_month_contract():
    # 2026-07-29 is 2 days from month-end => unstable to back out from July;
    # compute should use the August contract average as the post-meeting rate.
    settlements = {
        (2026, 7): 5.30,    # noisy meeting-month contract (ignored for end rate)
        (2026, 8): 5.625,   # clean post-meeting rate => +25bp vs 5.375 midpoint
    }
    res = fedwatch.compute(CFG, date(2026, 6, 22), settlements)
    assert res is not None
    assert res["meeting"] == "2026-07-29"
    assert res["method"] == "next-month contract"
    assert res["implied_end_rate"] == 5.625
    assert res["hike_odds_pct"] == 100.0


def test_compute_early_month_meeting_backs_out_from_meeting_month():
    # A hypothetical early-month meeting uses the meeting-month back-out.
    cfg = load_config()
    cfg._d["macro_fetch"]["fomc_meetings"] = ["2026-08-05"]
    avg = (5 * 5.375 + 26 * 5.625) / 31  # +25bp move on day 5 of a 31-day month
    res = fedwatch.compute(cfg, date(2026, 6, 22), {(2026, 8): avg})
    assert res["method"] == "meeting-month back-out"
    assert res["hike_odds_pct"] == 100.0
