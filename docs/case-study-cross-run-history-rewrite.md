# Case study: silent history rewrites caught by the cross-run watchdog

> **When:** 2026-09 (production A-share research pipeline)
> **Outcome:** a daily watchdog over vendor data detected two silent-rewrite
> incident classes across runs — a one-day ×100 OHLC corruption on 21
> symbols and a missing corporate-action event — by comparing each run's
> trailing closes against the previous run's state. Rewrites on days *after*
> the newest ex-date fire because nothing legitimate can change them
> between runs; the segment *before* the newest ex-date is exempt (a new
> ex-date re-anchors forward history) and is covered by the live-raw drift
> check instead.
> Reproduction: `python examples/case_history_rewrite.py` (offline, no deps).

## The problem

Vendor data changes shape between runs in two very different ways:

1. **Legitimate re-anchoring.** When a corporate action is recorded, the
   vendor re-serves the whole forward-adjusted (qfq) history: every bar
   before the new ex-date is rescaled. A detector that treats any change as
   a rewrite would fire on every new dividend — noise.
2. **Silent rewrites.** Sometimes history changes with no event behind it:
   a parser bug scales one day's OHLC ×100, a source mix-up rewrites a
   close, a vendor corrects (or corrupts) already-served values. A backtest
   that ran on the old values is now untrustworthy, and nothing in the file
   announces the change.

The two are indistinguishable on the pre-ex segment — both change it. They
are distinguishable on the **post-newest-ex-date segment**: after the newest
ex-date, forward prices equal raw prices, and no corporate action can touch
them. A change there, between two runs, with no new event in the archive,
is a rewrite.

## How `padj watch` works

Each run fingerprints the trailing bars' vendor closes (default: last 20,
rounded) into a state file (`watch_state.json`, keyed by `--code`):

```
padj watch --bars vendor_600000.json --actions actions.json \
  --as-of 2026-09-02 --state-dir ./watch-state --code 600000
```

The next run compares against the stored tail:

- days present in both tails, **on or after the newest archive ex-date**,
  whose close changed → `rewrites` listed, exit code 1 (FIRED);
- days before the newest ex-date → exempt (re-anchor segment; the
  `drift-check` vs live raw closes owns it);
- a new trading day at the tail → normal growth, never a rewrite;
- a day that disappeared → coverage change, not a rewrite.

Incremental-alert semantics: the check fires on the *delta* between runs —
if the rewritten value persists, the next run is silent again. No repeat
alerts for the same corruption.

## The fix pattern

1. **Detect**: `padj watch` FIRES with the changed dates (previous vs
   current close per day).
2. **Correlate**: group changed dates by bar `source` tag / vendor feed (a
   parser or fallback path, not the market).
3. **Repair**: restore the corrupted bars from an independent source; keep
   an append-only repair log; re-run `watch` — the repaired values change
   the tail exactly once and are then quiet.
4. **Regression-test the ingestion fix** so the rewrite class cannot
   re-enter silently; keep `watch` in the daily cron so any future rewrite
   is caught within one run-to-run interval.

## Tooling

- `padj watch` — stateful cross-run rewrite detection (per code; one state
  file serves many codes via `--code`).
- `python examples/case_history_rewrite.py` — six-run replay: baseline →
  unchanged → silent rewrite FIRED → persists (silent) → second rewrite
  FIRED → new ex-date re-anchor (exempt). Self-checking exit code.
