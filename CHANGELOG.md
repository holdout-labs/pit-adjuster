# Changelog

## [0.1.5] - 2026-09-06
- feat: `padj watch` — stateful cross-run history-rewrite detection.
  Each run fingerprints the trailing vendor closes into
  `<state-dir>/watch_state.json` (keyed by `--code`); a day whose close
  changed since the previous run, on or after the newest archive ex-date,
  is a silent history rewrite -> FIRED (exit 1).  Days before the newest
  ex-date are exempt — a new ex-date legitimately re-anchors forward
  history (that segment is `drift-check`'s job).  Incremental-alert
  semantics: a persisting rewritten value does not re-fire on the next
  run.  New APIs `tail_snapshot` and `detect_rewrites`.
- docs: real-world case study
  `docs/case-study-cross-run-history-rewrite.md` + offline reproduction
  `examples/case_history_rewrite.py` (six-run replay: baseline -> unchanged
  -> silent rewrite FIRED -> persists (silent) -> second rewrite FIRED ->
  new ex-date re-anchor (exempt), self-checking exit code).

## [0.1.4] - 2026-09-06
- feat: `padj forward-check` — validate a vendor forward-adjusted (qfq)
  series against the deterministic day returns implied by raw closes and
  the corporate-action archive.  Any fixed basis has identical day returns
  to raw on days with no corporate action, so a deviation on a non-event
  day is never a legitimate convention difference: deviations outside
  ±`event-window-days` of an archive ex-date are unexplained, and more than
  `--unexplained-limit` of them means `broken` (vendor forward-chain
  drift).  A CA archive that missed an event the vendor applied surfaces as
  a single unexplained jump (`suspicious`).  New API `check_forward_series`.
- docs: real-world case study `docs/case-study-vendor-forward-drift.md`
  (vendored forward chain drifting on event-dense codes — 6 of 8 sampled
  codes BROKEN, 32–424 unexplained drift days of 837) + offline
  reproduction `examples/case_forward_drift.py` (clean / broken /
  missing-event verdicts, self-checking exit code).

## [0.1.3] - 2026-09-05
- fix: `__version__` synced to pyproject (CLI `version` output was stale on
  PyPI builds); wheel-smoke CI job added (version consistency + fresh-venv
  install smoke).

## [0.1.2] - 2026-09-02
- fix: `compare_raw_closes`/`padj drift-check` default to the full series — the old trailing-5 default was vacuous whenever the latest ex-date lay behind the tail (regression found in production, dual-track with dongzhu qfq_drift_watch).
- fix: schema `$id` org residue `metabolism-tools` -> `holdout-labs`.
- docs: real-world case study (one-day ×100 price-scale corruption, 21 symbols) + offline reproduction `examples/case_scale_corruption.py`; companion reproduction for a missing corporate-action event; README.zh-CN.

## [0.1.1] / [0.1.0] - 2026-08-18
- Initial public release: PIT fixed-basis back-adjustment, factor chains, invert/drift checks, snapshot equivalence.
