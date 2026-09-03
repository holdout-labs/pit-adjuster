# Changelog

## [0.1.2] - 2026-09-02
- fix: `compare_raw_closes`/`padj drift-check` default to the full series — the old trailing-5 default was vacuous whenever the latest ex-date lay behind the tail (regression found in production, dual-track with dongzhu qfq_drift_watch).
- fix: schema `$id` org residue `metabolism-tools` -> `holdout-labs`.
- docs: real-world case study (one-day ×100 price-scale corruption, 21 symbols) + offline reproduction `examples/case_scale_corruption.py`; companion reproduction for a missing corporate-action event; README.zh-CN.

## [0.1.1] / [0.1.0] - 2026-08-18
- Initial public release: PIT fixed-basis back-adjustment, factor chains, invert/drift checks, snapshot equivalence.
