"""Unit tests for forward-series reconciliation (check_forward_series).

Motivating production failure (2026-09): a vendor's forward-adjusted (qfq)
chain drifted on corporate-action-dense codes — spurious day returns of
±0.3–2% on days with no corporate action (6 of 8 sampled codes BROKEN,
32–424 unexplained days).  ``check_forward_series`` classifies exactly that:
deviations from the deterministic day returns implied by raw closes, outside
an ex-date window, count as unexplained; more than ``unexplained_limit`` of
them means the vendor series is broken.
"""

from __future__ import annotations

from pit_adjuster.validation import check_forward_series

# Weekday-only calendar: Monday 2026-06-01 .. Friday 2026-06-26 (20 days).
DAYS = [
    "2026-06-01", "2026-06-02", "2026-06-03", "2026-06-04", "2026-06-05",
    "2026-06-08", "2026-06-09", "2026-06-10", "2026-06-11", "2026-06-12",
    "2026-06-15", "2026-06-16", "2026-06-17", "2026-06-18", "2026-06-19",
    "2026-06-22", "2026-06-23", "2026-06-24", "2026-06-25", "2026-06-26",
]
EVENT_DAY = "2026-06-15"
EVENT_FACTOR = 0.95  # e.g. cash dividend: reference-price factor applied by qfq


def _raw_closes(step: float = 0.002) -> dict[str, float]:
    """Raw closes that gap down by the dividend on the ex-date."""
    closes: dict[str, float] = {}
    previous = None
    for index, day in enumerate(DAYS):
        price = 10.0 * (1 + step) ** index
        if day == EVENT_DAY and previous is not None:
            price = previous * EVENT_FACTOR  # overnight reference-price gap
        closes[day] = round(price, 6)
        previous = price
    return closes


def _correct_forward(raw: dict[str, float]) -> dict[str, float]:
    """Vendor chain computed exactly: before the ex-date, scale by the
    factor of every future event (qfq convention); at/after it, unscaled."""
    return {
        day: round(close * (EVENT_FACTOR if day < EVENT_DAY else 1.0), 6)
        for day, close in raw.items()
    }


def _buggy_forward(raw: dict[str, float]) -> dict[str, float]:
    """Vendor bug: after the ex-date the chain keeps 'settling' — it applies
    an extra decaying re-anchoring for 10 trading days (0.5%/day), producing
    spurious day returns long after the event-window."""
    index = DAYS.index(EVENT_DAY)
    closes: dict[str, float] = {}
    for i, day in enumerate(DAYS):
        close = raw[day]
        if day < EVENT_DAY:
            close *= EVENT_FACTOR
        elif i > index:
            # extra multiplier decays 5% -> 0% over the next 10 trading days;
            # its per-day change (0.5%) shows up as a spurious day return.
            k = i - index
            extra = 1.0 + 0.05 * (1 - k / 10.0) if k <= 10 else 1.0
            close *= extra
        closes[day] = round(close, 6)
    return closes


def test_correct_forward_is_clean_event_only() -> None:
    raw = _raw_closes()
    report = check_forward_series(raw, _correct_forward(raw), [EVENT_DAY])
    assert report["verdict"] == "clean_event_only"
    assert report["unexplained_days"] == 0
    assert report["deviant_days"] == 1  # only the ex-date day
    assert report["explainable_days"] == 1
    assert report["checked"] == len(DAYS) - 1


def test_identical_series_without_events_is_clean() -> None:
    raw = _raw_closes()
    report = check_forward_series(raw, dict(raw), [])
    assert report["verdict"] == "clean"
    assert report["deviant_days"] == 0


def test_vendor_settling_drift_is_broken() -> None:
    """Days 3..10 after the ex-date deviate but are outside the +-2 day
    event window -> unexplained; more than the limit -> broken."""
    raw = _raw_closes()
    report = check_forward_series(raw, _buggy_forward(raw), [EVENT_DAY])
    assert report["verdict"] == "broken"
    assert report["unexplained_days"] > 2
    assert report["explainable_days"] >= 1
    # none of the unexplained days may sit inside the event window
    for row in report["unexplained"]:
        assert abs(DAYS.index(row["date"]) - DAYS.index(EVENT_DAY)) > 2


def test_missing_archive_event_surfaces_as_suspicious() -> None:
    """Vendor applied an event the archive does not know: its ex-date is not
    near any listed event -> exactly one unexplained day -> suspicious
    (mirrors the 2026-09 single-missing-event finding)."""
    raw = _raw_closes()
    report = check_forward_series(raw, _correct_forward(raw), [])  # archive empty
    assert report["verdict"] == "suspicious"
    assert report["unexplained_days"] == 1
    assert report["unexplained"][0]["date"] == EVENT_DAY


def test_tolerance_respects_small_noise() -> None:
    raw = _raw_closes()
    noisy = {day: round(close * 1.0001, 6) for day, close in _correct_forward(raw).items()}
    # tiny level noise changes no day returns -> still clean
    assert check_forward_series(raw, noisy, [EVENT_DAY])["verdict"] == "clean_event_only"
    # but a per-day 1% compounding noise is unexplained drift
    drift: dict[str, float] = {}
    for i, day in enumerate(DAYS):
        drift[day] = round(raw[day] * 1.01**i, 6)
    report = check_forward_series(raw, drift, [])
    assert report["verdict"] == "broken"


def test_coverage_counts_report_missing_days() -> None:
    raw = _raw_closes()
    forward = _correct_forward(raw)
    del forward[DAYS[-1]]
    report = check_forward_series(raw, forward, [EVENT_DAY])
    assert report["paired_days"] == len(DAYS) - 1
    assert report["raw_days"] == len(DAYS)
