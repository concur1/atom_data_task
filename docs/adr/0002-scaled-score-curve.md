# ADR 0002: Converting % correct to a KS2-style scaled score

- **Status:** accepted
- **Date:** 2026-11-15
- **Evidence:** [`notebooks/02_conversion_curves.py`](../../notebooks/02_conversion_curves.py),
  [`notebooks/03_reconciliation.py`](../../notebooks/03_reconciliation.py) §9

## Context

The brief asks for a SATs score on the 80-120 scale for every pupil in every
subject, using GOV.UK and external data to decide what a pupil's percentage
on an Atom assessment corresponds to.

What GOV.UK provides:

- **Conversion tables** for each year's KS2 tests: reading (/50), maths
  (/110) and grammar, punctuation & spelling (GPS, /70). They map raw marks to
  a scaled score of 80-120. Raw 0-2 gets no scaled score ("N"), and 100 is the
  expected standard. The raw mark needed for 100 changes every year (reading
  25-28, maths 54-58, GPS 34-35 over 2024-2026). We copied 2024-2026 into
  `reference_docs/` and the seed `ks2_scaled_score_conversion`.
- **The method behind the tables**, in STA's
  [National curriculum test handbook](https://dera.ioe.ac.uk//35121/1/2019_national_curriculum_test_handbook.pdf)
  (§13):
  1. In 2016 teacher panels set the expected standard (a "Bookmark" exercise
     on a two-parameter IRT model).
  2. Each later test is equated back to 2016 with anchor tests and a
     two-parameter graded response IRT model.
  3. The scale is **linear in IRT ability θ** (Equation 1):
     `SC = 100 + σ(SC)/σ(θ) · (θ − θ_cut)`, rounded down and capped to 80-120.

  The item parameters aren't published, so the tables can't be recomputed
  exactly.

The constraints:

- An Atom assessment is **not** a KS2 paper. Its questions, length and
  difficulty differ, so a KS2 table converts marks on a test we don't have.
- Atom has subjects with no KS2 test (Screeners, Verbal and Non-Verbal
  Reasoning), and the brief asks for every subject.
- The data is a small mock sample (164 pupils, years 1-6), not enough to
  calibrate a scale from.

## Options considered

| Option | How it works | Fit to official tables | Why not chosen |
|---|---|---|---|
| Real KS2 tables | Read % as % of KS2 marks off one year's table | exact (for that paper) | Calibrated to a specific KS2 paper, not an Atom assessment. No table for non-KS2 subjects. |
| Generic averaged curve | Average the three KS2 curves in % space | ~1 pt mean, max 4 | A derived lookup table; harder to explain than one formula. |
| 3-point formula | Straight lines through the 80 / 100 / 120 points | 1.1-3.2 pts mean, max 6 | Ignores the curve's shape. |
| **KS2-shaped logit formula** | Equation 1 with θ ≈ logit(p) | **0.5-1.5 pts mean, max 5** | **Chosen** |
| Atom difficulty-adjusted | Estimate question difficulty from Atom responses and adjust ability | n/a | Needs more data than this sample. Future step. |
| Full IRT / Rasch model | Fit an IRT model to Atom responses | n/a | Out of scope for this task. |

## Decision

**One formula for every subject, Maths and English included:**

```
p            = correct / questions                    (per sitting and subject)
scaled_score = N                                       if p < 0.05
             = 120                                     if p = 1
             = clamp(floor(100 + 7.3 · (logit(p) − logit(0.5))), 80, 120)   otherwise

logit(p)     = ln(p / (1 − p))
```

- **Why logit.** In IRT, `P(correct) = 1 / (1 + e^−(θ − b))`, so on a test of
  similar items `θ − b ≈ logit(p)`. Substituting into STA's Equation 1 gives the
  formula above. It keeps the shape of the official curves: steep near 0% and
  100%, flat in the middle.
- **Constants** come from the KS2 tables (more data than our sample), not from
  Atom data:
  - `k = 7.3` scaled points per logit: a single best fit across all nine
    2024-2026 tables.
  - `p_cut = 0.5`: the expected standard. The fit gives 0.498, and the fit for
    each table separately is 0.48-0.54. "About half the marks" in every
    subject and year.
  - `min_p = 0.05`: no score below this, in line with the KS2 minimum of 3 raw
    marks (2.7-6% of marks depending on subject).
- **Rounding** is down to the integer below, as STA does. Results are clamped
  to 80-120.
- **No score is never rounded up.** Below the minimum the result is `N`
  (null `scaled_score`), as in the GOV.UK guidance, not 80.
- **Where it lives.** The formula is one macro, `macros/ks2_scaled_score.sql`.
  The constants are dbt vars (`ks2_logit_slope`, `ks2_logit_p_cut`,
  `ks2_min_p`). Every output row records `scoring_method = 'ks2_logit_v1'`.
- **The official tables** are kept only as a seed, for calibration, tests and
  the comparison chart. Scoring never reads them.

### What counts as "correct" and "questions"

These are settled in ADR 0001 and the exploration notebook:

- One answer per (sitting, question). Duplicate copies count as correct only
  if every copy is correct.
- No-attempts count as wrong.
- Only scorable sittings are used: complete, not deleted, not survey or
  adaptive, year group ≤ 6.

## Evidence

- **Fitted per table**, the two-parameter formula reproduces the official
  tables almost exactly (mean error 0.15-0.44 points, max 1-3). The structure
  of Equation 1 with θ ≈ logit(p) describes the real curves.
- **The single formula** sits 0.6-1.5 points from the official tables on
  average (max 5, at the low end of maths). That's about the size of the
  year-to-year differences between the official tables themselves (mean
  0.4-1.8, max 4).
- **On Atom data:**
  - It agrees with reading Maths and English off the 2026 tables on "met the
    expected standard" for 95.6% and 100% of sittings respectively, with a
    mean gap under 1 point.
  - 16 of 2,303 scored sittings get `N`.
  - An independent Python recalculation matches every gold score.

## Consequences

- Every subject is scored the same way, and adding a subject needs no code.
- Scores are **"KS2-equivalent", not KS2 results.** They assume an Atom
  assessment is about as hard as a KS2 paper and one question is worth one
  mark (some KS2 questions are worth 2-3).
- Years 1-5 are scored on a scale designed for the end of year 6. The output
  carries `year_group_at_sitting` so consumers can filter or caveat.
- Scores for non-KS2 subjects (Screeners, Verbal and Non-Verbal Reasoning)
  have no national test behind them.
- The 2016 standard-setting exercise isn't reproduced. We inherit its result
  through the fitted curve.
- Short sittings give coarse scores (8 questions = steps of 12.5%). Question
  counts are kept in the output so reliability can be judged.
- Changing a constant changes every score. It must come with a new
  `scoring_method` value.

## Open

- **Missing questions.** 49 sittings have fewer answers than
  `total_questions`, with holes in `question_number`. `p` currently uses
  answered questions only. Counting missing questions as wrong would lower
  those scores.

## Not doing (yet)

- **Adjusting for question difficulty with Atom data.** Estimate each
  question's difficulty from Atom responses (`b_q = −logit(overall % correct)`)
  and use `logit(p) + mean(b_q)` as ability, keeping the same formula. This
  removes the "as hard as KS2" assumption once there's enough data.
- **Full IRT / Rasch model** of Atom items, the closest analogue of STA's
  method.
- **Recalibrating** `k` and `p_cut` when new KS2 tables are published (rerun
  the fit in `02_conversion_curves`, release as `ks2_logit_v2`).
