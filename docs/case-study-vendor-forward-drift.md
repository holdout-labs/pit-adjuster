# Case study: vendored forward chains drift on event-dense codes — caught by forward-check

> **When:** 2026-09 (production A-share research pipeline)
> **Outcome:** a cached vendor forward-adjusted (qfq) series for 5,500+ codes
> was found to be a *faithful mirror* of the vendor's own service — but the
> vendor's forward computation itself was broken on corporate-action-dense
> codes: 6 of 8 sampled codes BROKEN, with 32–424 unexplained drift days
> out of 837 (spurious ±0.3–2% day returns on days with no corporate
> action, spanning years). The cache was rebuilt deterministically from the
> corporate-action (CA) chain; the vendor forward series was not trusted.
> Reproduction: `python examples/case_forward_drift.py` (offline, no deps).

## The incident

A research pipeline cached each vendor's "forward" (前复权, qfq) daily closes
into per-code files and compared them against an independent corporate-action
chain built from a second source. The suspicion was cache staleness; the
three-way check (cache vs vendor-live vs CA chain) showed otherwise:

1. **The cache was faithful.** On the control code the cached series matched
   a freshly pulled vendor series day-for-day (0 differences across 881
   days) — so the cache was not stale and not mis-parsed.
2. **The vendor series itself was drifting.** Comparing vendor day returns
   against the deterministic day returns implied by raw closes × CA events,
   the drift pattern was unmistakable: the more corporate actions a code had
   (especially stock distributions / bonus issues), the heavier the drift.
   A six-event code had 436 drift days; a four-event pure-cash-dividend code
   had jumps only on its ex-dates (clean). Distribution-heavy chains
   suggest a compounding / re-anchoring defect on the vendor side — not
   something a consumer can repair by re-fetching.
3. **Event streams disagree in both directions.** Event-diff reconciliation
   also found a real corporate action (a per-share dividend) present in the
   vendor's event data but missing from the CA chain — corroborated by a
   third source. CA chains are not infallible; cross-checks matter.

## Why the check works

`padj forward-check` (0.1.4+) compares the vendor forward series against the
deterministic day returns implied by raw closes and the CA archive:

- Any fixed-basis adjusted series (hfq, qfq, current-vintage forward) has
  **identical day returns to raw on days with no corporate action** — an
  adjustment is a one-day re-basing. So a deviation on a non-event day is
  never a legitimate convention difference.
- Deviant days within ±`event-window-days` calendar days of an archive
  ex-date are explainable (vendors may lag or lead an ex-date by a day);
  everything else is **unexplained**.
- Verdict: `clean` / `clean_event_only` (only ex-date deviations — a vendor
  that applies exactly the archive factors) / `suspicious` (1..N unexplained
  days — e.g. an archive that *missed* an event the vendor applied) /
  `broken` (more than `unexplained-limit` unexplained days — vendor forward
  chain drift; do not trust the series).

Honest boundaries (documented in the function docstring): a *raw* series
mislabeled as forward also passes day-return checks (level checks belong to
`padj drift-check` vs live closes), and an archive event the vendor never
applied shows up as an event-window deviation at worst.

## The fix pattern

1. **Detect**: three-way reconciliation → BROKEN verdict with per-day
   unexplained rows (date, vendor return, raw return, deviation).
2. **Correlate**: drift days cluster after distribution/bonus events; sparse
   pure-cash codes stay clean → vendor-side forward-chain defect, not a
   cache bug.
3. **Rebuild deterministically**: derive the adjusted series from raw closes
   × CA events (single deterministic caliber); back up the old cache before
   replacing it; keep consumers unchanged.
4. **Cross-check events**: corroborate any one-off unexplained jump against
   independent event sources before rebuilding (a CA chain can be the one
   missing the event).

## Tooling

- `padj forward-check --raw raw.json --forward fwd.json --actions actions.json`
  — reconcile and classify (JSON / JSONL / date→close inputs accepted).
- `python examples/case_forward_drift.py` — offline reproduction of all
  three verdicts (consistent chain → `clean_event_only`; settling-bug chain
  → `broken`; archive missing an event → `suspicious`), self-checking exit.
