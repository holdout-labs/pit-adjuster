"""Reproduce the cross-run "silent history rewrite" case (offline).

A production A-share research pipeline keeps a daily watchdog over vendor
data.  In 2026-09 one incident class was a vendor silently *rewriting*
already-served history (a one-day x100 price-scale corruption on 21
symbols; a later case: a missing corporate-action event).  Detecting the
rewrite at ingestion time matters because a backtest that already ran on
the old values cannot be trusted once history changes under it.

``padj watch`` semantics (0.1.5+): each run fingerprints the trailing vendor
closes into a state file; a day whose close changed since the previous run,
on or after the newest archive ex-date, is a silent history rewrite (FIRED).
Days before the newest ex-date are exempt — a new ex-date legitimately
re-anchors the whole forward-adjusted history (that segment is the job of
``padj drift-check`` vs live raw closes).

This script replays six consecutive runs of the watchdog over one code:

1. baseline run                          -> ok (no baseline yet)
2. next day, data unchanged              -> ok
3. vendor silently rewrote a post-ex bar -> FIRED (1 rewritten day)
4. same (corrupted) data persists        -> ok (incremental alert: no repeat)
5. vendor rewrote a second bar           -> FIRED again
6. archive gains a new event; the vendor
   re-anchors history (pre-ex closes
   change)                               -> ok (legitimate re-anchor)

Run with:  python examples/case_history_rewrite.py
No network, no third-party dependencies.  Exits 1 when any of the six
behaviours does not hold (self-check).
"""

from __future__ import annotations

import datetime
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pit_adjuster.chain import events_from_actions  # noqa: E402
from pit_adjuster.validation import detect_rewrites, tail_snapshot  # noqa: E402

CODE = "600000"
AS_OF = "2026-07-31"
FIRST_EX = "2026-06-15"  # newest archive ex-date during runs 1-5


def _weekdays(start: str, count: int) -> list[str]:
    days: list[str] = []
    day = datetime.date.fromisoformat(start)
    while len(days) < count:
        if day.weekday() < 5:
            days.append(day.isoformat())
        day += datetime.timedelta(days=1)
    return days


DAYS = _weekdays("2026-06-01", 40)


def _action(ex_date: str, factor: float) -> dict:
    return {
        "action_id": f"test-{ex_date}",
        "action_type": "cash_dividend_stock_distribution",
        "ex_date": ex_date,
        "available_at": ex_date,
        "adjustment_factor": factor,
    }


def _bars(closes: dict[str, float]) -> list[dict]:
    return [{"date": day, "close": closes[day]} for day in DAYS]


def _trend() -> dict[str, float]:
    return {day: round(10.0 + 0.02 * i, 4) for i, day in enumerate(DAYS)}


def _watch_round(
    state: dict[str, Any],
    closes: dict[str, float],
    actions: list[dict],
) -> tuple[bool, list[dict[str, Any]], str | None]:
    """One watchdog run over one code (state transition mirrors padj watch)."""
    events = events_from_actions(actions, as_of_date=AS_OF)
    newest_ex = events[-1]["ex_date"] if events else None
    tail = tail_snapshot(_bars(closes))
    previous = state.get(CODE)
    previous_tail = previous.get("tail") if isinstance(previous, dict) else None
    rewrites = detect_rewrites(previous_tail, tail, newest_ex=newest_ex)
    state[CODE] = {"tail": tail, "newest_ex": newest_ex, "run_as_of": AS_OF}
    return bool(rewrites), rewrites, newest_ex


def main() -> int:
    state: dict[str, Any] = {}
    actions = [_action(FIRST_EX, 0.95)]
    closes = _trend()
    checks_ok = True

    def round_label(step: str, fired: bool, rewrites: list[dict], newest_ex) -> None:
        tail_note = f"{len(rewrites)} day(s): " + ", ".join(
            f"{row['date']} {row['previous_close']}->{row['current_close']}"
            for row in rewrites
        )
        print(f"  {step}: {'FIRED' if fired else 'ok'}  "
              f"(newest_ex={newest_ex}, {tail_note if rewrites else 'no rewrite'})")

    # 1. baseline
    fired, rows, newest_ex = _watch_round(state, closes, actions)
    round_label("1. baseline run (no previous state)", fired, rows, newest_ex)
    checks_ok = checks_ok and not fired and not state[CODE]["tail"] == {}

    # 2. unchanged next day
    fired, rows, newest_ex = _watch_round(state, closes, actions)
    round_label("2. next day, data unchanged", fired, rows, newest_ex)
    checks_ok = checks_ok and not fired

    # 3. vendor silently rewrites a post-ex bar (no new event)
    rewritten = closes.copy()
    day_a = DAYS[-3]
    rewritten[day_a] = round(rewritten[day_a] * 1.03, 4)
    fired, rows, newest_ex = _watch_round(state, rewritten, actions)
    round_label("3. post-ex bar silently rewritten", fired, rows, newest_ex)
    checks_ok = checks_ok and fired and len(rows) == 1 and rows[0]["date"] == day_a

    # 4. the corrupted value persists -> no repeat alert
    fired, rows, newest_ex = _watch_round(state, rewritten, actions)
    round_label("4. same data persists (incremental alert)", fired, rows, newest_ex)
    checks_ok = checks_ok and not fired

    # 5. vendor rewrites a second bar
    day_b = DAYS[-1]
    rewritten[day_b] = round(rewritten[day_b] * 0.97, 4)
    fired, rows, newest_ex = _watch_round(state, rewritten, actions)
    round_label("5. second bar silently rewritten", fired, rows, newest_ex)
    checks_ok = checks_ok and fired and len(rows) == 1 and rows[0]["date"] == day_b

    # 6. a new corporate action arrives: vendor re-anchors pre-ex history
    new_ex = DAYS[28]
    actions2 = actions + [_action(new_ex, 0.9)]  # e.g. 10 -> 11.11 bonus issue
    reanchored = rewritten.copy()
    for day in DAYS:
        if day < new_ex:
            reanchored[day] = round(reanchored[day] * 0.9, 4)
    fired, rows, newest_ex = _watch_round(state, reanchored, actions2)
    round_label("6. new ex-date re-anchors history (exempt)", fired, rows, newest_ex)
    checks_ok = checks_ok and not fired and newest_ex == new_ex

    print(
        "\nverdict:",
        "watch catches silent rewrites once and ignores legitimate re-anchors"
        if checks_ok
        else "FAILED — watch did not behave as expected",
    )
    return 0 if checks_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
