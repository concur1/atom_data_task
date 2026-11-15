# ADR 0002: Converting % correct to a KS2-style scaled score

- **Status:** accepted
- **Date:** 2026-11-15
- **Evidence:** [`notebooks/02_conversion_curves.py`](../../notebooks/02_conversion_curves.py)
  (section 9 for the chosen formula)

## Context

The brief asks for a SATs score on the 80-120 scale for every pupil in every
subject, using GOV.UK and external data to decide what a pupil's percentage
on an Atom assessment corresponds to.

GOV.UK publishes **conversion tables** for each year's KS2 tests: reading
(out of 50), maths (out of 110) and grammar, punctuation and spelling (GPS,
out of 70).

- They map a raw mark to a scaled score from 80 to 120.
- A raw score of 0-2 gets no scaled score ("N").
- 100 is the expected standard. The raw mark needed for it changes every year
  (2024-2026: reading 25-28, maths 54-58, GPS 34-35), but it is always about
  half the marks.
- We copied the 2024-2026 tables into `reference_docs/` and the seed
  `ks2_scaled_score_conversion`.

The constraints:

- **An Atom assessment is not a KS2 paper.** Its questions, length and
  difficulty differ, so a KS2 table converts marks on a test we don't have.
- **Some Atom subjects have no KS2 test** (Screeners, Verbal and Non-Verbal
  Reasoning), and the brief asks for every subject.
- **The data is a small mock sample** (164 pupils, years 1-6), not enough to
  calibrate our own scale.

## Decision

Use **linear rescaling** (min-max scaling) of the proportion correct onto the
80-120 scale, the same for every subject. With $p$ = the proportion of
questions answered correctly in a sitting:

```math
\text{scaled score} =
\begin{cases}
\text{N (no score)} & p < 0.05 \\
\lfloor 80 + 40p \rfloor & \text{otherwise}
\end{cases}
```

So 0% maps to 80, 50% to 100 (the expected standard) and 100% to 120; each
2.5% correct is one scaled point.

| % correct | 10 | 25 | 40 | 50 | 60 | 75 | 90 |
|---|---|---|---|---|---|---|---|
| Scaled score | 84 | 90 | 96 | 100 | 104 | 110 | 116 |

- **Why linear:** it is the most standard tool for putting a percentage on a
  different range, has no fitted constants, needs no clamping and is easy to
  explain. It matches the two facts the KS2 tables agree on every year: the
  scale runs 80-120, and the expected standard is about half the marks.
- **Rounding** is down to the integer below, as STA does for KS2. It's
  computed in integer arithmetic, `80 + div(40 * correct, questions)`, so
  there is no floating-point rounding.
- **Below the minimum** (5% correct, mirroring the KS2 rule that 3 raw marks
  are needed for any score, 2.7-6% of the marks) there is no score:
  `has_scaled_score = false` and `scaled_score` is null. It is never rounded
  up to 80.
- **Where it lives:** one macro, `macros/ks2_scaled_score.sql`, with the
  minimum as a dbt var (`ks2_min_pct: 5`). Every output row records
  `scoring_method = 'linear_v1'`.
- **The official tables** are kept only as a seed, for checks and comparison
  charts. Scoring never reads them.

What counts as "correct" and "questions" is settled in ADR 0001: one answer
per (sitting, question), where duplicate copies count as correct only if every
copy is correct; no-attempts count as wrong; only scorable sittings are used.

## How it compares with the official tables

Against all nine 2024-2026 tables, over the raw scores that get a score
(`notebooks/02_conversion_curves.py`, section 9):

| Subject | Mean error (points) | Max error | Agrees on "met the expected standard" |
|---|---|---|---|
| GPS | 0.9-1.1 | 3 | 98.5-100% of raw scores |
| Reading | 0.9-1.4 | 3 | 93.8-100% |
| Maths | 1.9-2.4 | 5 | 97.1-99.0% |
| **All** | **1.55** | **5** | |

- For comparison, the official tables differ from each other year to year by
  0.4-1.8 points on average (max 4).
- **Maths** is the weakest fit. Its curve is flat in the middle and steep at
  the ends, so a straight line is about 1.8 points harsh below 20% and about
  2.6 points generous above 80%. GPS comes out slightly harsh throughout,
  reading slightly generous.
- **On Atom data**, compared with reading Maths and English off the 2026
  tables, the mean gap is 2.0 points for Maths and 0.7 for English. The two
  agree on "met the expected standard" for 95.6% and 100% of sittings.

## Options considered

| Option | Fit to official tables (mean / max) | Verdict |
|---|---|---|
| Read % off one year's real KS2 table | exact, for that paper | Rejected: calibrated to a specific KS2 paper, not an Atom assessment; no table for non-KS2 subjects. |
| Average of the three KS2 curves | about 1 / 4 | Rejected: a derived lookup table, harder to explain. |
| **Linear rescaling, 80 + 40p** | **1.55 / 5** | **Chosen:** standard, no fitted constants. |
| Linear, fitted (82.5 + 35p, clamped) | 1.33 / 5 | Rejected: fitted constants for little gain. |
| Logit formula (below) | 0.97 / 5 | Rejected: about 0.6 points more accurate, but needs a derivation and two fitted constants. |
| Probit, 100 + 12.1·z(p) | 0.96 / 4 | Rejected: reads like a norm-referenced standardised score, which it isn't. |
| Adjust for question difficulty with Atom data | n/a | Later: needs more data than this sample. |

### The logit alternative, and where it comes from

The more faithful alternative follows STA's documented method. The
[National curriculum test handbook](https://dera.ioe.ac.uk//35121/1/2019_national_curriculum_test_handbook.pdf)
(section 13) says KS2 scaled scores are a **linear transformation of IRT
ability** (their Equation 1, rounded down):

```math
SC_i = 100 + \frac{\sigma(SC)}{\sigma(\theta)}\,\big(\theta_{X_i} - \theta_{cut}\big)
```

In a two-parameter IRT model, the chance of a correct answer is
$P(\theta) = 1 / (1 + e^{-a(\theta - b)})$. On a test of similar questions,
inverting it gives ability as a straight line in the log-odds of the
proportion correct, $\theta \approx b + \operatorname{logit}(p)/a$ with
$\operatorname{logit}(p) = \ln\frac{p}{1-p}$. With varied question
difficulties the same form holds with a wider slope (the "PROX" approximation;
Wright and Stone, *Best Test Design*, 1979). Substituting gives

```math
SC \approx 100 + k\,\big(\operatorname{logit}(p) - \operatorname{logit}(p_{cut})\big)
```

with $k = 7.3$ and $p_{cut} = 0.5$ fitted to the nine tables. Fitted per table
it reproduces them almost exactly (0.15-0.44 points), which shows the S-shape
of the tables comes from the raw-mark-to-ability relationship. We chose the
linear formula anyway: it's simpler and more standard, and the logit's extra
accuracy (about 0.6 points on average) is small next to the assumption that
an Atom assessment behaves like a KS2 paper at all.

## Consequences

- Every subject is scored the same way, and adding a subject needs no code.
- Scores are **"KS2-equivalent", not KS2 results.** They assume an Atom
  assessment is about as hard as a KS2 paper and that one question is worth
  one mark (some KS2 questions are worth 2-3).
- Linear rescaling ignores the S-shape of the real curves, so scores near the
  extremes differ most from what a KS2 table would give, especially for maths.
- Years 1-5 are scored on a scale designed for the end of year 6. The output
  carries `year_group_at_sitting` so consumers can filter or caveat.
- Scores for Screeners and Verbal and Non-Verbal Reasoning have no national
  test behind them.
- Short sittings give coarse scores (8 questions = steps of 12.5%, i.e. 5
  scaled points). Question counts are kept in the output so reliability can
  be judged.
- Changing the formula changes every score, so it must come with a new
  `scoring_method` value.

## Missing questions

49 sittings have fewer answers than `total_questions`, with holes in
`question_number`. $p$ uses the **answered questions only** (missing questions
are treated as not asked). Counting them as wrong would lower those scores,
but we can't tell whether a question was skipped or simply never recorded.

## Not doing (yet)

- **Adjusting for question difficulty with Atom data.** Estimate each
  question's difficulty from Atom responses and adjust each pupil's result
  before rescaling. This would remove the "as hard as KS2" assumption once
  there's enough data.
- **Switching to the logit formula** if the extra accuracy at the extremes
  ever matters more than simplicity (`scoring_method = 'logit_v1'`).
