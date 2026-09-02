"""Reproduce the missing-corporate-action-event case (offline).

Companion to ``case_scale_corruption.py``. In the same production run that
caught the x100 scale corruption, the watchdog surfaced a second signature:
a real ex-date was absent from the point-in-time corporate-action archive,
while the vendor's qfq history already carried the adjustment. Rebuilding
with the (incomplete) archive leaves every PRE-event bar inverted to
``raw x factor`` instead of ``raw``, so the drift comparison reports a
constant deviation of ``1 - factor`` on the whole pre-event segment.

This script builds a synthetic history with that shape and shows:

1. a tail-only comparison (sample_days=5, the pre-0.1.2 default) reports 0.0
   and MISSES the event, because the corrupted segment sits before the
   trailing window (post-event qfq equals raw, so the tail is vacuous);
2. the full-window default reports worst_deviation ~0.3155 (1 - 0.6845)
   and FIRES, with the constant-deviation signature that distinguishes a
   missing event from a single-bar scale corruption.

Run with:  python examples/case_missing_event.py
No network, no third-party dependencies.  Exits 1 when the detection does
not fire (self-check).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pit_adjuster.chain import rebuild_bars  # noqa: E402
from pit_adjuster.validation import compare_raw_closes  # noqa: E402

AS_OF = "2026-09-02"
EVENT_DATE = "2026-06-10"  # real ex-date, deliberately missing from the archive
FACTOR = 0.6845  # vendor qfq history already carries this adjustment


def _bar(day: str, close: float) -> dict:
    return {
        "date": day,
        "open": close,
        "high": round(close * 1.01, 4),
        "low": round(close * 0.99, 4),
        "close": close,
        "volume": 250000.0,
        "amount": round(close * 250000.0 * 100.0, 2),  # volume is in lots
        "turnover": 1.5,
        "source": "vendor_daily",
    }


def main() -> int:
    # 60 daily bars; a real ex-date at EVENT_DATE (June 10) with factor
    # 0.6845 — old enough that the trailing 5 bars are all post-event.
    # Vendor qfq (current vintage): pre-event bars = raw x factor,
    # post-event bars = raw. The archive knows nothing about the event.
    days = []
    for month, day in [
        ("06", d) for d in range(1, 31)
    ] + [("07", d) for d in range(1, 31)]:
        days.append(f"2026-{month}-{day:02d}")

    live: dict[str, float] = {}
    bars: list[dict] = []
    for i, day in enumerate(days):
        raw = round(5.0 + 0.01 * i, 4)
        live[day] = raw
        close = round(raw * FACTOR, 4) if day < EVENT_DATE else raw
        bars.append(_bar(day, close))

    rebuilt, _ = rebuild_bars(bars, [], as_of_date=AS_OF)

    tail_only = compare_raw_closes(rebuilt, live, sample_days=5)
    full = compare_raw_closes(rebuilt, live)

    pre_event_devs = [
        row["deviation"]
        for row in full["rows"]
        if row["date"] < EVENT_DATE
    ]
    signature = (
        f"constant {round(max(pre_event_devs), 4)} on {len(pre_event_devs)} pre-event bars"
        if pre_event_devs
        else "no pre-event deviation"
    )

    print(f"bars: {len(bars)}  event date: {EVENT_DATE} (missing from archive)")
    print(f"tail-only (old default): checked={tail_only['checked']} "
          f"worst={tail_only['worst_deviation']}  -> "
          f"{'MISSED (vacuous)' if not tail_only['worst_deviation'] else 'FIRED'}")
    print(f"full-window (0.1.2 default): checked={full['checked']} "
          f"worst={full['worst_deviation']}  -> "
          f"{'FIRED' if full['worst_deviation'] and full['worst_deviation'] > 0.01 else 'missed'}")
    print(f"signature: {signature}  (missing event = constant pre-event block, "
          f"not a single-bar spike)")

    fired = bool(full["worst_deviation"]) and full["worst_deviation"] > 0.01
    print("verdict:", "detection works" if fired else "FAILED TO FIRE")
    return 0 if fired else 1


if __name__ == "__main__":
    raise SystemExit(main())
