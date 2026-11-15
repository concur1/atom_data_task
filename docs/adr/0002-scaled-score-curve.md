# ADR 0002: Converting % correct to a KS2-style scaled score

- **Status:** accepted
- **Date:** 2026-11-15
- **Evidence:** [`notebooks/02_conversion_curves.py`](../../notebooks/02_conversion_curves.py)
  and [`notebooks/03_reconciliation.py`](../../notebooks/03_reconciliation.py) (section 9)

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
  (2024-2026: reading 25-28, maths 54-58, GPS 34-35).
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

Use one formula for every subject, Maths and English included. With
$p$ = the proportion of questions answered correctly in a sitting:

```math
\text{scaled score} =
\begin{cases}
\text{N (no score)} & p < 0.05 \\
120 & p = 1 \\
\min\Big(120,\ \max\big(80,\ \big\lfloor 100 + 7.3\,\big(\operatorname{logit}(p) - \operatorname{logit}(0.5)\big) \big\rfloor\big)\Big) & \text{otherwise}
\end{cases}
\qquad
\operatorname{logit}(p) = \ln\frac{p}{1-p}
```

Since $\operatorname{logit}(0.5) = 0$, in SQL this is:

```sql
least(120, greatest(80, floor(100 + 7.3 * ln(p / (1 - p)))))
```

Some values:

| % correct | 10 | 25 | 40 | 50 | 60 | 75 | 90 |
|---|---|---|---|---|---|---|---|
| Scaled score | 83 | 91 | 97 | 100 | 102 | 108 | 116 |

- **Constants** come from the official KS2 tables, which rest on far more data
  than our sample. Section "Fitting the constants" explains each one.
- **Rounding** is down to the integer below, as STA does, and the result is
  clamped to 80-120.
- **Below the minimum** the result is `N` (null `scaled_score`), as in the
  GOV.UK guidance. It is never rounded up to 80.
- **Where it lives:** one macro, `macros/ks2_scaled_score.sql`. The constants
  are dbt vars (`ks2_logit_slope`, `ks2_logit_p_cut`, `ks2_min_p`), and every
  output row records `scoring_method = 'ks2_logit_v1'`.
- **The official tables** are kept only as a seed, for calibration, checks and
  the comparison chart. Scoring never reads them.

What counts as "correct" and "questions" is settled in ADR 0001: one answer
per (sitting, question), where duplicate copies count as correct only if every
copy is correct; no-attempts count as wrong; only scorable sittings are used.

## Where the formula comes from

The formula is **our derivation**, not something STA publishes. It combines
STA's documented scaling method with a standard approximation from item
response theory (IRT).

### 1. STA's scale is a straight line in ability

STA's
[National curriculum test handbook](https://dera.ioe.ac.uk//35121/1/2019_national_curriculum_test_handbook.pdf)
(section 13, "Standard setting and standards maintenance") describes how the
tables are made:

- **2016:** panels of teachers set the expected standard with a "Bookmark"
  exercise, ordering items with "a two-parameter IRT model".
- **2017 onwards:** each new test is equated back to 2016 using anchor tests
  and "a multiple-group, two-parameter graded response IRT model".
- **Scaling:** "A linear IRT scale transformation was used" (their Equation 1):

```math
SC_i = 100 + \frac{\sigma(SC)}{\sigma(\theta)}\,\big(\theta_{X_i} - \theta_{cut}\big)
```

where $\theta_{X_i}$ is the IRT ability for raw score $X_i$ and
$\theta_{cut}$ the ability at the expected standard. "Scaled scores were
rounded down to the integer below."

So **the scaled score is linear in ability $\theta$, not in raw marks.** The
S-shape of the tables, when plotted against % of marks, comes from the link
between raw marks and ability.

### 2. Ability is roughly the log-odds of % correct

In a two-parameter IRT model, the chance that a pupil of ability $\theta$
answers question $i$ correctly is

```math
P_i(\theta) = \frac{1}{1 + e^{-a_i(\theta - b_i)}}
```

where $b_i$ is the question's difficulty and $a_i$ its discrimination. If the
questions on a test are similar ($a_i \approx a$, $b_i \approx b$), a pupil's
proportion correct $p$ follows the same curve, and inverting it gives

```math
\theta \approx b + \frac{1}{a}\,\operatorname{logit}(p)
```

When question difficulties vary, the standard normal approximation (the
"PROX" estimate; Wright and Stone, *Best Test Design*, 1979) keeps the same
form with a wider slope:

```math
\theta \approx \bar{b} + \sqrt{1 + \frac{\sigma_b^2}{2.89}}\;\operatorname{logit}(p)
```

Either way, **ability is a straight line in $\operatorname{logit}(p)$.**

### 3. Substitute into STA's equation

Putting step 2 into step 1, every constant collapses into two:

```math
SC \approx 100 + k\,\big(\operatorname{logit}(p) - \operatorname{logit}(p_{cut})\big)
```

- $k$ (scaled points per logit) absorbs STA's $\sigma(SC)/\sigma(\theta)$ and
  the test's item discrimination and spread.
- $p_{cut}$ is the proportion correct at the expected standard
  ($\theta_{cut}$).

STA doesn't publish item parameters, so $k$ and $p_{cut}$ can't be computed
directly. We fit them to the published tables instead.

### 4. Fitting the constants

Grid search for the $(k, p_{cut})$ that minimises the mean absolute error
against the tables (`notebooks/02_conversion_curves.py`, section 7):

| | $k$ | $p_{cut}$ | Mean error (points) | Max error |
|---|---|---|---|---|
| Each table fitted on its own | 5.8-8.3 | 0.48-0.54 | 0.15-0.44 | 1-3 |
| **One formula for all nine tables** | **7.3** | **0.498** | 0.96 | 5 |

- Fitted per table, the formula reproduces the official tables almost
  exactly. That confirms the derivation describes how the real curves behave.
- $k$ is lower for maths (about 6) than for reading and GPS (about 8). That's
  consistent with step 2: a test with a wider spread of question difficulty
  has a flatter curve.
- We use the single formula so every subject is treated the same. $p_{cut}$ is
  rounded to 0.5 ("about half the marks", true of every table).
- $\min_p = 0.05$ mirrors the KS2 rule that 3 raw marks are needed for any
  score, which is 2.7-6% of the marks depending on subject.

## Options considered

| Option | Fit to official tables | Verdict |
|---|---|---|
| Read % off one year's real KS2 table | exact, for that paper | Rejected: calibrated to a specific KS2 paper, not an Atom assessment; no table for non-KS2 subjects. |
| Average of the three KS2 curves | about 1 point mean, max 4 | Rejected: a derived lookup table, harder to explain than one formula. |
| Straight lines through the 80, 100 and 120 points | 1.1-3.2 points mean, max 6 | Rejected: ignores the curve's shape. |
| **KS2-shaped logit formula** | **0.6-1.5 points mean, max 5** | **Chosen.** |
| Adjust for question difficulty with Atom data | n/a | Later: needs more data than this sample. |
| Full IRT (Rasch) model of Atom items | n/a | Out of scope for this task. |

## Evidence

- **Against the official tables**, the single formula is 0.6-1.5 points off on
  average (max 5, at the low end of maths). That's about the size of the
  official tables' own year-to-year differences (mean 0.4-1.8, max 4).
- **On Atom data**, compared with reading Maths and English off the 2026
  tables, it agrees on "met the expected standard" for 95.6% (Maths) and 100%
  (English) of sittings, with a mean gap under 1 point.
- 16 of the 2,303 scored sittings get `N`.
- An independent Python recalculation matches every score in gold.

## Consequences

- Every subject is scored the same way, and adding a subject needs no code.
- Scores are **"KS2-equivalent", not KS2 results.** They assume an Atom
  assessment is about as hard as a KS2 paper and that one question is worth
  one mark (some KS2 questions are worth 2-3).
- Years 1-5 are scored on a scale designed for the end of year 6. The output
  carries `year_group_at_sitting` so consumers can filter or caveat.
- Scores for Screeners and Verbal and Non-Verbal Reasoning have no national
  test behind them.
- The 2016 standard-setting exercise isn't reproduced; we inherit its result
  through the fitted curve.
- Short sittings give coarse scores (8 questions = steps of 12.5%). Question
  counts are kept in the output so reliability can be judged.
- Changing a constant changes every score, so it must come with a new
  `scoring_method` value.

## Open

- **Missing questions.** 49 sittings have fewer answers than
  `total_questions`, with holes in `question_number`. $p$ currently uses
  answered questions only; counting the missing ones as wrong would lower
  those scores.

## Not doing (yet)

- **Adjusting for question difficulty with Atom data.** Estimate each
  question's difficulty from Atom responses and use the PROX form in step 2
  (mean difficulty plus scaled $\operatorname{logit}(p)$) as ability, keeping
  the same scale. This removes the "as hard as KS2" assumption once there's
  enough data.
- **A full IRT (Rasch) model** of Atom items, the closest analogue of STA's
  method.
- **Recalibrating** $k$ and $p_{cut}$ when new KS2 tables are published: rerun
  the fit in `02_conversion_curves` and release as `ks2_logit_v2`.
