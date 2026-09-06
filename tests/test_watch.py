"""Unit + CLI tests for cross-run history-rewrite detection (padj watch).

The stateful watchdog semantics (distilled from a production qfq drift
watchdog, 2026-09): each run fingerprints the trailing vendor closes; a day
whose close changed since the previous run, on or after the newest archive
ex-date, is a silent history rewrite (no new corporate action can explain
it).  Days before the newest ex-date are exempt — a new ex-date legitimately
re-anchors the whole forward-adjusted history.
"""

from __future__ import annotations

import datetime
import json

import pytest

from pit_adjuster.cli import main
from pit_adjuster.validation import detect_rewrites, tail_snapshot

NEWEST_EX = "2026-06-15"


def _weekdays(start: str, count: int) -> list[str]:
    days: list[str] = []
    day = datetime.date.fromisoformat(start)
    while len(days) < count:
        if day.weekday() < 5:
            days.append(day.isoformat())
        day += datetime.timedelta(days=1)
    return days


DAYS = _weekdays("2026-06-01", 30)  # 2026-06-01 .. ~2026-07-10


def _bars(closes: dict[str, float]) -> list[dict]:
    return [{"date": day, "close": closes[day]} for day in DAYS]


def _trend() -> dict[str, float]:
    return {day: round(10.0 + 0.02 * i, 4) for i, day in enumerate(DAYS)}


def _action(ex_date: str, factor: float = 0.95) -> dict:
    return {
        "action_id": f"test-{ex_date}",
        "action_type": "cash_dividend",
        "ex_date": ex_date,
        "available_at": ex_date,
        "adjustment_factor": factor,
    }


# --- pure functions ---------------------------------------------------------


def test_tail_snapshot_keeps_last_n_and_rounds() -> None:
    closes = _trend()
    tail = tail_snapshot(_bars(closes), limit=10)
    assert len(tail) == 10
    assert tail[DAYS[-1]] == round(closes[DAYS[-1]], 4)


def test_detect_rewrites_no_baseline_or_same_tail() -> None:
    tail = tail_snapshot(_bars(_trend()))
    assert detect_rewrites(None, tail, newest_ex=NEWEST_EX) == []
    assert detect_rewrites(tail, dict(tail), newest_ex=NEWEST_EX) == []


def test_detect_rewrites_fires_on_post_ex_change() -> None:
    closes = _trend()
    previous = tail_snapshot(_bars(closes))
    changed_day = DAYS[-1]  # well after NEWEST_EX
    closes[changed_day] = round(closes[changed_day] * 1.03, 4)
    current = tail_snapshot(_bars(closes))
    rows = detect_rewrites(previous, current, newest_ex=NEWEST_EX)
    assert len(rows) == 1
    assert rows[0]["date"] == changed_day
    assert rows[0]["previous_close"] != rows[0]["current_close"]


def test_detect_rewrites_exempts_pre_ex_changes() -> None:
    """A new ex-date re-anchors pre-ex history: days before the (new) newest
    ex-date are exempt from rewrite detection."""
    closes = _trend()
    previous = tail_snapshot(_bars(closes))
    new_ex = DAYS[25]  # an event between the two runs, inside the tail
    for day in DAYS:
        if day < new_ex:
            closes[day] = round(closes[day] * 0.95, 4)  # legitimate re-anchor
    current = tail_snapshot(_bars(closes))
    assert detect_rewrites(previous, current, newest_ex=new_ex) == []
    # same change judged against an older newest ex would fire:
    assert detect_rewrites(previous, current, newest_ex=NEWEST_EX) != []


def test_detect_rewrites_checks_all_when_no_ex_date() -> None:
    closes = _trend()
    previous = tail_snapshot(_bars(closes))
    changed_day = DAYS[20]  # inside the default 20-bar tail
    closes[changed_day] = round(closes[changed_day] * 1.1, 4)
    current = tail_snapshot(_bars(closes))
    rows = detect_rewrites(previous, current, newest_ex=None)
    assert [row["date"] for row in rows] == [changed_day]


def test_detect_rewrites_ignores_dropped_days() -> None:
    """A day missing from the current tail is coverage change, not a
    rewrite of a value the vendor still serves."""
    closes = _trend()
    previous = tail_snapshot(_bars(closes))
    current = dict(previous)
    current.pop(DAYS[-1])
    assert detect_rewrites(previous, current, newest_ex=NEWEST_EX) == []


# --- CLI end-to-end ---------------------------------------------------------


@pytest.fixture()
def watch_env(tmp_path):
    bars = _bars(_trend())
    bars_path = tmp_path / "bars.json"
    actions_path = tmp_path / "actions.json"
    bars_path.write_text(json.dumps(bars), encoding="utf-8")
    actions_path.write_text(json.dumps([_action(NEWEST_EX)]), encoding="utf-8")
    state_dir = tmp_path / "state"
    return {
        "bars": str(bars_path),
        "actions": str(actions_path),
        "state_dir": str(state_dir),
        "tmp": tmp_path,
    }


def _run_watch(env, bars, capsys):
    bars_path = env["tmp"] / "bars.json"
    bars_path.write_text(json.dumps(bars), encoding="utf-8")
    code = main(
        [
            "watch",
            "--bars", str(bars_path),
            "--actions", env["actions"],
            "--as-of", "2026-07-31",
            "--state-dir", env["state_dir"],
            "--code", "TEST1",
        ]
    )
    return code, capsys.readouterr().out


def test_cli_watch_fires_once_then_stays_silent(watch_env, capsys) -> None:
    """Baseline run ok; a silent post-ex rewrite FIRES once; the persisting
    value does not re-fire on the next run (incremental alert)."""
    closes = _trend()
    code, out = _run_watch(watch_env, _bars(closes), capsys)
    assert code == 0
    assert '"fired": false' in out

    changed_day = DAYS[-1]
    closes[changed_day] = round(closes[changed_day] * 1.03, 4)
    code, out = _run_watch(watch_env, _bars(closes), capsys)
    assert code == 1
    assert '"fired": true' in out
    assert changed_day in out

    code, out = _run_watch(watch_env, _bars(closes), capsys)
    assert code == 0
    assert '"rewritten_days": 0' in out


def test_cli_watch_new_ex_date_reanchor_is_exempt(watch_env, capsys) -> None:
    """A new archive event re-anchors pre-ex history; watch must not fire."""
    closes = _trend()
    _run_watch(watch_env, _bars(closes), capsys)

    new_ex = DAYS[15]
    actions_path = watch_env["tmp"] / "actions.json"
    actions_path.write_text(
        json.dumps([_action(NEWEST_EX), _action(new_ex)]), encoding="utf-8"
    )
    for day in DAYS:
        if day < new_ex:
            closes[day] = round(closes[day] * 0.95, 4)
    code, out = _run_watch(watch_env, _bars(closes), capsys)
    assert code == 0
    assert '"newest_ex": "%s"' % new_ex in out


def test_cli_watch_state_keyed_by_code(watch_env, capsys) -> None:
    """Two codes share one state file without cross-talk."""
    closes = _trend()
    _run_watch(watch_env, _bars(closes), capsys)  # code TEST1 baseline
    bars_path = watch_env["tmp"] / "bars.json"
    code = main(
        [
            "watch",
            "--bars", str(bars_path),
            "--actions", watch_env["actions"],
            "--as-of", "2026-07-31",
            "--state-dir", watch_env["state_dir"],
            "--code", "TEST2",
        ]
    )
    assert code == 0
    state = json.loads(
        (watch_env["tmp"] / "state" / "watch_state.json").read_text(encoding="utf-8")
    )
    assert set(state["codes"]) == {"TEST1", "TEST2"}
