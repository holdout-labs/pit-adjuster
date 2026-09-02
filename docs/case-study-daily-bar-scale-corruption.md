# Case study: a one-day ×100 price-scale corruption caught by drift-check

> **When:** 2026-09 (production A-share research pipeline)
> **Outcome:** 21 symbols' daily OHLC for a single trading day were stored ×100
> (e.g. close `4.02` → `402.0`) while volume/amount stayed correct. A
> full-window drift comparison (the `compare_raw_closes` semantics behind
> `padj drift-check`) fired with a ~99× worst deviation, the corrupted bars
> were repaired from an independent raw source, and the ingestion bug class
> was fixed and regression-tested.
> Reproduction: `python examples/case_scale_corruption.py` (offline, no deps).

## The incident

A production A-share research pipeline ingests vendor daily bars
("qfq current vintage") into per-symbol history files. One evening the usual
full-universe drift check — rebuild each symbol's history with the
point-in-time corporate-action archive, then compare the inverted raw closes
against a live unadjusted close source — reported `worst_deviation = 99.0`
for 21 symbols, all dated the same trading day.

Investigation showed:

1. Only **21 of ~1,760 symbols** were affected, and every affected bar had the
   same `source` tag: a realtime-batch fallback path that the pipeline uses
   when the primary kline endpoint is unreachable. That path had been silent
   for weeks (the primary source usually responds); on this day it answered
   for exactly these 21 symbols.
2. Prices were exactly ×100 (OHLC `402.0` vs true `4.02`), while
   `amount ≈ close_true × volume × 100` — i.e. **only OHLC were corrupted**,
   not volume/amount. That pattern is the signature of a parser that forgot a
   ×100 field-scale normalisation (such realtime-quote fields carry prices in
   cent-like units and turnover in 0.01% units).
3. The corruption was invisible to any consumer that only reads *returns*
   (a constant scale factor cancels), but it silently poisons anything that
   reads absolute prices or mixes sources.

## Why the check fired (and why the 0.1.2 default matters)

The detection runs the comparison over the **whole provided series**, not just
the trailing N bars:

- A trailing-5 sampling default is vacuous whenever the divergence lives on
  bars older than the tail window (after an ex-date, qfq prices equal raw
  prices, so a tail-only window reports 0.0 even for a rewritten history).
  This is why 0.1.2 changed `compare_raw_closes`/`padj drift-check` to compare
  the full series by default (`--sample-days` remains as an explicit
  tail-only opt-in).
- A scale corruption of an *old* bar is exactly such a case: the corrupted day
  may sit far behind the trailing window, and only a full-window comparison
  sees the ~99× step against the live source.

## The fix pattern

1. **Detect**: full-universe drift run → FIRED with per-symbol worst deviation
   and worst date.
2. **Correlate**: group by bar `source` tag → every affected bar came from one
   fallback path → the parser, not the market, was at fault.
3. **Repair data**: overwrite the corrupted OHLC from an independent
   unadjusted-close source; keep volume/amount (they were correct); log the
   repair append-only with before/after values.
4. **Fix code**: normalise the ×100-scaled fields (`price/100`, `turnover/100`)
   in the parser and add a regression test that pins the scale semantics —
   the previous test suite had baked in the *unscaled* assumption, which is
   how the bug survived.
5. **Re-verify**: rerun the full drift check → worst deviation returns to the
   normal dividend-modelling noise band (≈0.1–0.7% on symbols with cash
   dividends, 0 on symbols without events).

## Cross-cutting lessons

- **Absolute-price checks earn their keep**: return-based sanity checks cannot
  see a constant scale corruption; comparing *inverted* raw closes against a
  live unadjusted source can.
- **Fallback paths are where scale bugs hide**: an occasionally-used source
  with different field conventions is a latent corruption generator. Audit
  every fallback's units (price scale, volume lot vs share, turnover meaning)
  and pin them with tests.
- **Repair provenance**: keep the repair log (old/new OHLC + source + factor)
  next to the detector's artifacts so the evidence chain is replayable.

The same detector family also caught, in the same production run, a missing
corporate-action event (a real ex-date absent from the archive source, visible
as a constant ~31% deviation on every bar before the event) — see
`examples/` for the scale-corruption reproduction and the tool's
`compare_raw_closes`/`compare_snapshots` API for building the equivalent
guards in your own pipeline.

## Companion reproduction: the missing-event signature

The missing-event failure has a different fingerprint from the scale
corruption, and the same default catches both:

```bash
python examples/case_missing_event.py
# → tail-only: MISSED (vacuous) / full-window: FIRED (0.3155)
# → signature: constant 0.3155 on 9 pre-event bars
```

The scenario: the vendor's qfq history already carries a real ex-date
(factor 0.6845) but the point-in-time archive knows nothing about it, so
every **pre-event** bar inverts to `raw × 0.6845` instead of `raw` — a
constant `1 − 0.6845 = 0.3155` deviation across the whole pre-event
segment, vs. the single-bar ~99× spike of the scale-corruption case. Read
the signatures, not just the numbers: **a single-bar spike is a price
corruption; a constant pre-event block is a missing event.** Tail-only
sampling misses both whenever the divergence sits before the trailing
window.
