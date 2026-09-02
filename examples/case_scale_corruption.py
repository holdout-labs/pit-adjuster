"""Reproduce the 2026-09 ×100 scale-corruption case (offline).

A production A-share pipeline stored one trading day's OHLC ×100 for 21
symbols (close 4.02 -> 402.0) while volume/amount stayed correct.  This
script rebuilds a synthetic history with the same shape — one old bar whose
OHLC is ×100 — and shows:

1. a tail-only comparison (sample_days=5, the pre-0.1.2 default) reports
   0.0 and MISSES the corruption, because the corrupted bar is older than
   the trailing window;
2. the full-window default (0.1.2+) reports worst_deviation ~99 and FIRES.

Run with:  python examples/case_scale_corruption.py
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
CORRUPT_DAY = "2026-06-15"  # deliberately NOT in the trailing 5 bars
SCALE = 100.0


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
    # 30 daily bars, no corporate actions: qfq == raw, close drifts ~4.0 -> 4.6.
    days = [f"2026-06-{d:02d}" for d in range(1, 16)] + [
        f"2026-06-{d:02d}" for d in range(16, 31)
    ]
    live: dict[str, float] = {}
    bars: list[dict] = []
    for i, day in enumerate(days):
        close = round(4.0 + 0.02 * i, 4)
        live[day] = close
        bars.append(_bar(day, close))
    # Incident: one old bar's OHLC stored ×100 (volume/amount untouched).
    for bar in bars:
        if bar["date"] == CORRUPT_DAY:
            bar["open"] = round(bar["open"] * SCALE, 4)
            bar["high"] = round(bar["high"] * SCALE, 4)
            bar["low"] = round(bar["low"] * SCALE, 4)
            bar["close"] = round(bar["close"] * SCALE, 4)

    rebuilt, _ = rebuild_bars(bars, [], as_of_date=AS_OF)

    tail_only = compare_raw_closes(rebuilt, live, sample_days=5)
    full = compare_raw_closes(rebuilt, live)

    print(f"bars: {len(bars)}  corrupted day: {CORRUPT_DAY}")
    print(f"tail-only (old default): checked={tail_only['checked']} "
          f"worst={tail_only['worst_deviation']}  -> "
          f"{'MISSED (vacuous)' if not tail_only['worst_deviation'] else 'FIRED'}")
    print(f"full-window (0.1.2 default): checked={full['checked']} "
          f"worst={full['worst_deviation']}  -> "
          f"{'FIRED' if full['worst_deviation'] and full['worst_deviation'] > 0.01 else 'missed'}")

    fired = bool(full["worst_deviation"]) and full["worst_deviation"] > 0.01
    print("verdict:", "detection works" if fired else "FAILED TO FIRE")
    return 0 if fired else 1


if __name__ == "__main__":
    raise SystemExit(main())
