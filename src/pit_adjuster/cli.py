"""Command-line interface for pit-adjuster.

Subcommands:

- ``rebuild``                rebuild bars to fixed-basis hfq (PIT)
- ``invert-check``           ex-date continuity sanity check
- ``drift-check``            static forward-adjustment detection vs live closes
- ``forward-check``          vendor forward series vs CA archive (day-return
                             reconciliation, unexplained-day verdict)
- ``watch``                  cross-run history-rewrite detection (stateful
                             watchdog: last-state tail vs current tail)
- ``snapshot-equivalence``   before/after equivalence of two rebuilds
- ``version``                print version
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path
from typing import Any

from . import __version__
from .chain import events_from_actions, rebuild_bars
from .io import load_actions, load_bars, write_json
from .validation import (
    check_forward_series,
    compare_raw_closes,
    compare_snapshots,
    detect_rewrites,
    tail_snapshot,
    validate_inversion,
)


def _print_summary(heading: str, body: dict[str, Any]) -> None:
    print(f"== {heading} ==")
    print(json.dumps(body, ensure_ascii=False, indent=2))


def _add_common_inputs(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--bars", required=True, help="bars JSON/JSONL path")
    parser.add_argument("--actions", required=True, help="corporate-action archive JSON/JSONL path")
    parser.add_argument("--as-of", required=True, help="PIT cutoff date (YYYY-MM-DD)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="padj",
        description="Point-in-time fixed-basis back-adjustment engine.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    rebuild = sub.add_parser("rebuild", help="rebuild bars to fixed-basis hfq (PIT)")
    _add_common_inputs(rebuild)
    rebuild.add_argument("--code", default=None, help="instrument code (prefix rules for volume)")
    rebuild.add_argument("--volume-to-shares", type=float, default=None, help="override volume multiplier")
    rebuild.add_argument("--out", default=None, help="output path (JSON); default: stdout summary")

    invert = sub.add_parser("invert-check", help="ex-date continuity sanity check")
    _add_common_inputs(invert)
    invert.add_argument("--tolerance", type=float, default=0.03)

    drift = sub.add_parser("drift-check", help="static forward-adjustment detection vs live closes")
    _add_common_inputs(drift)
    drift.add_argument("--live", required=True, help="live raw closes JSON (date -> close)")
    drift.add_argument(
        "--sample-days",
        type=int,
        default=None,
        help="compare only the trailing N bars (default: whole series — "
        "trailing-only windows miss drift whose ex-date lies behind the tail)",
    )

    forward = sub.add_parser(
        "forward-check",
        help=(
            "validate a vendor forward-adjusted (qfq) series against the "
            "CA archive: day-return reconciliation with an "
            "unexplained-day BROKEN verdict"
        ),
    )
    forward.add_argument(
        "--raw", required=True,
        help="raw closes: JSON list of {date,close} / JSONL / date->close map",
    )
    forward.add_argument(
        "--forward", required=True,
        help="vendor forward-adjusted (qfq) closes, same formats as --raw",
    )
    forward.add_argument("--actions", required=True,
                         help="corporate-action archive JSON/JSONL path")
    forward.add_argument("--as-of", default=None,
                         help="PIT cutoff for archive events (YYYY-MM-DD); default: all")
    forward.add_argument("--tolerance", type=float, default=0.003,
                         help="day-return deviation threshold (default 0.003)")
    forward.add_argument("--event-window-days", type=int, default=2,
                         help="+/-calendar days around an ex-date counted as explainable")
    forward.add_argument("--unexplained-limit", type=int, default=2,
                         help="unexplained days above this -> broken")
    forward.add_argument("--out", default=None,
                         help="output path (JSON); default: stdout summary")

    watch = sub.add_parser(
        "watch",
        help=(
            "cross-run history-rewrite detection (stateful watchdog): "
            "compare this run's vendor close tail against the last run's "
            "state; changed days on/after the newest ex-date are silent "
            "history rewrites (FIRED)"
        ),
    )
    _add_common_inputs(watch)
    watch.add_argument("--state-dir", required=True,
                       help="directory holding watch_state.json (created if missing)")
    watch.add_argument("--code", default="default",
                       help="state key when one state file watches many codes")
    watch.add_argument("--tail-bars", type=int, default=20,
                       help="trailing bars fingerprinted per run (default 20)")
    watch.add_argument("--out", default=None,
                       help="output path (JSON); default: stdout summary")

    snap = sub.add_parser("snapshot-equivalence", help="before/after equivalence of two rebuilds")
    snap.add_argument("--before", required=True, help="rebuilt bars JSON (old pipeline)")
    snap.add_argument("--after", required=True, help="rebuilt bars JSON (new pipeline)")
    snap.add_argument("--tolerance", type=float, default=1e-6)

    sub.add_parser("version", help="print version")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "version":
        print(__version__)
        return 0

    if args.command == "rebuild":
        bars = load_bars(args.bars)
        actions = load_actions(args.actions)
        new_bars, stats = rebuild_bars(
            bars,
            actions,
            as_of_date=args.as_of,
            code=args.code,
            volume_to_shares=args.volume_to_shares,
        )
        if args.out:
            write_json(args.out, new_bars)
            print(f"rebuild: {stats['bars']} bars, {stats['invalid_bars']} invalid -> {args.out}")
        else:
            _print_summary(f"rebuild ({stats['bars']} bars, {stats['invalid_bars']} invalid)", new_bars[-5:])
        return 0

    if args.command == "invert-check":
        bars = load_bars(args.bars)
        actions = load_actions(args.actions)
        violations = validate_inversion(bars, actions, as_of_date=args.as_of, tolerance=args.tolerance)
        if violations:
            _print_summary(f"invert-check: {len(violations)} violation(s)", {"violations": violations})
            return 1
        print("invert-check: ok (no ex-date continuity violations)")
        return 0

    if args.command == "drift-check":
        bars = load_bars(args.bars)
        actions = load_actions(args.actions)
        live = _load_closes(args.live)
        report = compare_raw_closes(bars, live, sample_days=args.sample_days)
        _print_summary("drift-check", report)
        if report["worst_deviation"] is not None and report["worst_deviation"] > 0.01:
            return 1
        return 0

    if args.command == "forward-check":
        raw = _load_closes(args.raw)
        forward = _load_closes(args.forward)
        actions = load_actions(args.actions)
        events = events_from_actions(actions, as_of_date=args.as_of or "9999-12-31")
        report = check_forward_series(
            raw,
            forward,
            [event["ex_date"] for event in events],
            tolerance=args.tolerance,
            event_window_days=args.event_window_days,
            unexplained_limit=args.unexplained_limit,
        )
        if args.out:
            write_json(args.out, report)
            print(
                f"forward-check: {report['verdict']} "
                f"({report['unexplained_days']} unexplained of "
                f"{report['deviant_days']} deviant days) -> {args.out}"
            )
        else:
            _print_summary("forward-check", report)
        return 0 if report["verdict"] in ("clean", "clean_event_only") else 1

    if args.command == "watch":
        return cmd_watch(args)

    if args.command == "snapshot-equivalence":
        before = load_bars(args.before)
        after = load_bars(args.after)
        report = compare_snapshots(before, after, tolerance=args.tolerance)
        _print_summary("snapshot-equivalence", report)
        return 0 if report["equal"] else 1

    parser.error(f"unknown command: {args.command}")
    return 2


def _load_closes(path: str) -> dict[str, float]:
    """Load closes from a JSON date->close map, a JSON/JSONL list of rows
    with ``date`` + ``close``, or a JSON list of bars.  Keys are truncated to
    the date part."""
    import os

    rows: list[Any] = []
    if path.endswith(".jsonl"):
        with open(path, "r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
    elif os.path.exists(path):
        with open(path, "r", encoding="utf-8") as handle:
            loaded = json.load(handle)
        if isinstance(loaded, dict):
            return {str(key)[:10]: float(value) for key, value in loaded.items()}
        if isinstance(loaded, list):
            rows = loaded
    closes: dict[str, float] = {}
    for row in rows:
        if isinstance(row, dict) and row.get("date"):
            closes[str(row["date"])[:10]] = float(row["close"])
    if not closes and not (path.endswith(".jsonl") or os.path.exists(path)):
        raise ValueError(
            f"closes must be a JSON object mapping date -> close, a JSON/JSONL "
            f"list of {{date, close}}, or a JSON list of bars: {path}"
        )
    if not closes and rows:
        raise ValueError(
            f"closes source contains no {{date, close}} rows: {path}"
        )
    return closes


WATCH_STATE_SCHEMA_VERSION = "pit_adjuster.watch_state.v1"
WATCH_RECORD_SCHEMA_VERSION = "pit_adjuster.watch_record.v1"
WATCH_STATE_FILENAME = "watch_state.json"


def cmd_watch(args: argparse.Namespace) -> int:
    """Cross-run history-rewrite detection for one code (stateful watchdog).

    Watches the *vendor series as ingested* (the bars you feed to
    ``padj rebuild`` / ``drift-check``).  Each run fingerprints the trailing
    bars' closes into ``<state-dir>/watch_state.json`` under ``--code``;
    days whose close changed since the previous run, on or after the newest
    archive ex-date, are silent history rewrites -> FIRED (exit 1).  Days
    before the newest ex-date are exempt — a new ex-date legitimately
    re-anchors forward-adjusted history; that segment is the job of
    ``drift-check`` against live raw closes.  Incremental semantics: if the
    rewritten value persists, the next run is silent again.
    """
    bars = load_bars(args.bars)
    actions = load_actions(args.actions)
    events = events_from_actions(actions, as_of_date=args.as_of)
    newest_ex = events[-1]["ex_date"] if events else None
    tail = tail_snapshot(bars, limit=args.tail_bars)

    state_dir = Path(args.state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    state_path = state_dir / WATCH_STATE_FILENAME
    state: dict[str, Any] = {}
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            state = {}
    if not isinstance(state, dict):
        state = {}
    codes = state.get("codes") if isinstance(state.get("codes"), dict) else {}
    previous = codes.get(args.code)
    previous_tail = previous.get("tail") if isinstance(previous, dict) else None

    rewrites = detect_rewrites(previous_tail, tail, newest_ex=newest_ex)
    record: dict[str, Any] = {
        "schema_version": WATCH_RECORD_SCHEMA_VERSION,
        "code": args.code,
        "as_of": args.as_of,
        "checked_at": datetime.datetime.now().astimezone().isoformat(
            timespec="seconds"
        ),
        "tail_days": len(tail),
        "newest_ex": newest_ex,
        "had_baseline": isinstance(previous_tail, dict) and bool(previous_tail),
        "rewrites": rewrites,
        "rewritten_days": len(rewrites),
        "fired": bool(rewrites),
        "note": (
            "fired: close changed on a day on/after the newest archive "
            "ex-date with no new corporate action to explain it — history "
            "was silently rewritten. Days before newest_ex are exempt (a "
            "new ex-date legitimately re-anchors forward history); that "
            "segment is covered by drift-check vs live raw closes."
        ),
    }
    codes[args.code] = {
        "tail": tail,
        "newest_ex": newest_ex,
        "run_as_of": args.as_of,
    }
    state["schema_version"] = WATCH_STATE_SCHEMA_VERSION
    state["codes"] = codes
    write_json(state_path, state)

    if args.out:
        write_json(args.out, record)
        print(
            f"watch[{args.code}]: {'FIRED' if record['fired'] else 'ok'} "
            f"({record['rewritten_days']} rewritten days, "
            f"newest_ex={newest_ex}) -> {args.out}"
        )
    else:
        _print_summary(f"watch[{args.code}]", record)
    return 1 if record["fired"] else 0


if __name__ == "__main__":
    sys.exit(main())
