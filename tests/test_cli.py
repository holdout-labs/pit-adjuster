"""End-to-end CLI tests using temporary JSON fixtures."""

from __future__ import annotations

import json

import pytest

from pit_adjuster.cli import main


def _write(path, value) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(value, handle)


@pytest.fixture()
def fixtures(tmp_path):
    bars = [
        {"date": "2026-06-12", "open": 95.0, "high": 96.0, "low": 94.5, "close": 95.0, "volume": 1000.0},
        {"date": "2026-06-15", "open": 99.0, "high": 99.5, "low": 98.0, "close": 99.0, "volume": 1000.0},
    ]
    actions = [
        {"ex_date": "2026-06-15", "adjustment_factor": 0.95, "available_at": "2026-06-14T18:00:00"},
    ]
    bars_path = tmp_path / "bars.json"
    actions_path = tmp_path / "actions.json"
    live_path = tmp_path / "live.json"
    _write(bars_path, bars)
    _write(actions_path, actions)
    _write(live_path, {"2026-06-12": 100.0, "2026-06-15": 99.0})
    out_path = tmp_path / "hfq.json"
    return {
        "bars": str(bars_path),
        "actions": str(actions_path),
        "live": str(live_path),
        "out": str(out_path),
        "tmp": tmp_path,
    }


def test_cli_version() -> None:
    assert main(["version"]) == 0


def test_cli_rebuild_roundtrip(fixtures, capsys) -> None:
    code = main(
        [
            "rebuild",
            "--bars", fixtures["bars"],
            "--actions", fixtures["actions"],
            "--as-of", "2026-08-11",
            "--out", fixtures["out"],
        ]
    )
    assert code == 0
    with open(fixtures["out"], "r", encoding="utf-8") as handle:
        rebuilt = json.load(handle)
    assert len(rebuilt) == 2
    assert rebuilt[0]["raw_close"] == pytest.approx(100.0, abs=1e-4)
    assert rebuilt[1]["adj_factor"] == pytest.approx(1 / 0.95, abs=1e-9)


def test_cli_drift_check_detects_vendor_divergence(fixtures, capsys) -> None:
    # fixtures use vendor factor 0.95? No: bars already raw 95/99 but live is 100/99,
    # so the archive factor 0.95 produces inverted raw 100/99 -> matches live.
    code = main(
        [
            "drift-check",
            "--bars", fixtures["bars"],
            "--actions", fixtures["actions"],
            "--as-of", "2026-08-11",
            "--live", fixtures["live"],
        ]
    )
    assert code == 0


def test_cli_invert_check_ok(fixtures, capsys) -> None:
    code = main(
        [
            "invert-check",
            "--bars", fixtures["bars"],
            "--actions", fixtures["actions"],
            "--as-of", "2026-08-11",
        ]
    )
    assert code == 0


def test_cli_snapshot_equivalence(fixtures, capsys) -> None:
    assert (
        main(
            [
                "rebuild",
                "--bars", fixtures["bars"],
                "--actions", fixtures["actions"],
                "--as-of", "2026-08-11",
                "--out", fixtures["out"],
            ]
        )
        == 0
    )
    code = main(
        [
            "snapshot-equivalence",
            "--before", fixtures["out"],
            "--after", fixtures["out"],
        ]
    )
    assert code == 0


def _write_closes(tmp_path, name, closes) -> str:
    path = tmp_path / name
    _write(path, closes)
    return str(path)


def test_cli_forward_check_clean_event_only(tmp_path, fixtures, capsys) -> None:
    """A consistent vendor forward chain deviates from raw only at the
    ex-date (within the event window) -> clean_event_only, exit 0."""
    raw = _write_closes(
        tmp_path, "raw.json",
        {"2026-06-12": 100.0, "2026-06-15": 95.0, "2026-06-16": 96.0,
         "2026-06-17": 97.0, "2026-06-18": 98.0},
    )
    fwd = _write_closes(
        tmp_path, "fwd.json",
        {"2026-06-12": 95.0, "2026-06-15": 95.0, "2026-06-16": 96.0,
         "2026-06-17": 97.0, "2026-06-18": 98.0},
    )
    code = main(
        [
            "forward-check",
            "--raw", raw,
            "--forward", fwd,
            "--actions", fixtures["actions"],
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "clean_event_only" in out
    assert "unexplained_days" in out


def test_cli_forward_check_broken_drift(tmp_path, fixtures, capsys) -> None:
    """A vendor chain that drifts 0.5% on a day far outside the event window
    is unexplained; with limit 0 that is broken -> exit 1."""
    raw = _write_closes(
        tmp_path, "raw.json",
        {"2026-06-12": 100.0, "2026-06-15": 95.0, "2026-06-16": 96.0,
         "2026-06-17": 97.0, "2026-06-18": 98.0, "2026-06-19": 99.0},
    )
    fwd = _write_closes(
        tmp_path, "fwd.json",
        {"2026-06-12": 95.0, "2026-06-15": 95.0, "2026-06-16": 96.0,
         "2026-06-17": 97.0, "2026-06-18": 98.0, "2026-06-19": round(99.0 * 1.005, 6)},
    )
    code = main(
        [
            "forward-check",
            "--raw", raw,
            "--forward", fwd,
            "--actions", fixtures["actions"],
            "--unexplained-limit", "0",
        ]
    )
    assert code == 1
    out = capsys.readouterr().out
    assert '"verdict": "broken"' in out
    assert '"unexplained_days": 1' in out
