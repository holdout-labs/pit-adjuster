"""Reproduce the 2026-09 "vendored forward chain drift" case (offline).

A production A-share research pipeline cached a vendor's forward-adjusted
(qfq) daily series for 5,500+ codes.  A three-way reconciliation against a
deterministic corporate-action (CA) chain found the cache was a *faithful
mirror* of the vendor's own series — but the vendor's forward computation
itself was broken on corporate-action-dense codes: 6 of 8 sampled codes
showed unexplained day returns of +-0.3..2% on days with no corporate
action (32..424 drift days out of 837, spanning years).  The whole cache
was rebuilt from the CA chain; the vendor series was not trustworthy.

This script rebuilds the same shape with a synthetic code (four corporate
actions, incl. a stock distribution) and shows what ``check_forward_series``
(0.1.4+) does:

1. a *consistent* vendor chain deviates from raw only on ex-dates ->
   verdict ``clean_event_only``;
2. the same code with a vendor "settling" bug (extra decaying re-anchoring
   after each event) -> verdict ``broken`` with unexplained days far from
   any ex-date;
3. an archive that *misses* an event the vendor applied -> the single
   unexplained jump surfaces as ``suspicious`` (the 2026-09 single-missing-
   event finding: corroborate before rebuilding).

Run with:  python examples/case_forward_drift.py
No network, no third-party dependencies.  Exits 1 when any of the three
behaviours does not hold (self-check).
"""

from __future__ import annotations

import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pit_adjuster.validation import check_forward_series  # noqa: E402

EVENTS = [  # (ex_date, adjustment factor, note)
    ("2026-03-10", 0.95, "cash dividend"),
    ("2026-04-22", 0.7143, "stock distribution 10 -> 14 (factor = 1/1.4)"),
    ("2026-06-03", 0.92, "cash dividend"),
    ("2026-07-15", 0.96, "cash dividend"),
]


def _trading_days(start: str, count: int) -> list[str]:
    days: list[str] = []
    day = datetime.date.fromisoformat(start)
    while len(days) < count:
        if day.weekday() < 5:
            days.append(day.isoformat())
        day += datetime.timedelta(days=1)
    return days


def _raw_closes(days: list[str]) -> dict[str, float]:
    """Raw closes trending up, gapping down by each event's factor on its
    ex-date (the exchange reference-price gap)."""
    closes: dict[str, float] = {}
    previous = None
    event_factors = {ex: factor for ex, factor, _ in EVENTS}
    for index, day in enumerate(days):
        price = 10.0 * (1.0015 ** index)
        if day in event_factors and previous is not None:
            price = previous * event_factors[day]
        closes[day] = round(price, 6)
        previous = closes[day]
    return closes


def _vendor_series(
    raw: dict[str, float], days: list[str], *, settling_days: int = 0
) -> dict[str, float]:
    """Current-vintage forward chain: pre-ex-date prices scaled by every
    future event factor (qfq convention).  ``settling_days>0`` simulates the
    vendor bug: after each event the chain keeps re-anchoring with an extra
    decaying multiplier (~0.7%/trading day) for that many days, producing
    spurious day returns far from any ex-date."""
    event_factors = {ex: factor for ex, factor, _ in EVENTS}
    closes: dict[str, float] = {}
    for index, day in enumerate(days):
        scale = 1.0
        for ex, factor in event_factors.items():
            if day < ex:
                scale *= factor
        close = raw[day] * scale
        if settling_days:
            latest_ex = max(
                (ex for ex in event_factors if ex < day), default=None
            )
            if latest_ex is not None:
                elapsed = index - days.index(latest_ex)
                if 0 < elapsed <= settling_days:
                    close *= 1.0 + 0.08 * (1 - elapsed / (settling_days + 1))
        closes[day] = round(close, 6)
    return closes


def main() -> int:
    days = _trading_days("2026-01-05", 150)
    raw = _raw_closes(days)
    event_dates = [ex for ex, _, _ in EVENTS]
    checks_ok = True

    def show(title: str, verdict: str, report: dict) -> None:
        print(
            f"\n{title}\n"
            f"  verdict: {verdict}\n"
            f"  checked {report['checked']} day-pairs, "
            f"{report['deviant_days']} deviant "
            f"({report['explainable_days']} on event-window days), "
            f"{report['unexplained_days']} unexplained"
        )
        for row in report["unexplained"][:6]:
            print(f"    unexplained {row['date']}: "
                  f"forward {row['forward_return']:+.4%} vs "
                  f"raw {row['raw_return']:+.4%}")

    # 1. consistent vendor chain: deviations only at the four ex-dates.
    consistent = _vendor_series(raw, days)
    report = check_forward_series(raw, consistent, event_dates)
    show("1. consistent vendor chain (4 corporate actions)", report["verdict"], report)
    ok = report["verdict"] == "clean_event_only" and report["unexplained_days"] == 0
    checks_ok = checks_ok and ok
    print("   ->", "ok" if ok else "FAILED (regression)")

    # 2. vendor settling bug after every event -> spurious day returns.
    buggy = _vendor_series(raw, days, settling_days=10)
    report = check_forward_series(raw, buggy, event_dates)
    show("2. same code, vendor 'settling' bug after each event",
         report["verdict"], report)
    ok = report["verdict"] == "broken" and report["unexplained_days"] > 2
    checks_ok = checks_ok and ok
    print("   ->", "ok" if ok else "FAILED (regression)")

    # 3. archive missing an event the vendor applied -> one unexplained jump.
    partial_events = event_dates[:-1]  # archive lost the last event
    report = check_forward_series(raw, consistent, partial_events)
    show("3. archive missing the last event (vendor applied it)",
         report["verdict"], report)
    ok = report["verdict"] == "suspicious" and report["unexplained_days"] == 1
    checks_ok = checks_ok and ok
    print("   ->", "ok" if ok else "FAILED (regression)")

    print(
        "\nverdict:",
        "forward-check catches vendor forward-chain drift"
        if checks_ok
        else "FAILED — forward-check did not behave as expected",
    )
    return 0 if checks_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
