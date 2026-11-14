# ADR 0001: Scoring data model and point-in-time semantics

- **Status:** accepted
- **Date:** 2026-11-14

## Context

We produce a KS2-style scaled score (80-120) for every pupil in every subject
from Atom assessment responses (see `notebooks/01_exploration.py` and
`notebooks/02_conversion_curves.py`). The models must be:

- **re-runnable**: two runs give the same result
- **point-in-time**: we can recompute a pupil's score as it stood at time T
- **fit for the production application database**
- **able to scale**: `responses` will grow by more than 100m rows

The raw tables (`de_raw`) record when things happened (`started_at`,
`finished_at`, `answered_at`) but not when rows were loaded or changed. Every
complete sitting has a `finished_at`, and every sitting covers one subject.

## Decision

### Point in time means event time

The score as of T is computed from the sittings that **finished at or before
T**. It is the pupil's actual score at T, not "what the warehouse believed at T".

- Deletions and corrections apply **retroactively**. If a sitting or pupil is
  deleted, as-of queries for earlier dates change too.
- The guarantee: **for given source data, the score as of T is reproducible.**
- No snapshots of the source tables are kept.

### Lineage

```
source de_raw ─┬─ silver__sittings        one row per sitting: scoring rules as flags
               ├─ silver__answers         one row per (sitting, question): duplicates collapsed
               └─ silver__sitting_scores  one row per scorable sitting: questions, correct, p, scaled score
                            └─ gold__<name tbd>  type-2 history per pupil × subject
```

- **`silver__sittings`** keeps every sitting, with `is_scorable` and an
  `exclusion_reason`: `incomplete`, `deleted`, `survey`, `adaptive`,
  `year_group_above_6` or `no_responses`. Sittings of deleted pupils are dropped
  here, so a deleted pupil disappears from everything downstream, history
  included.
- **`silver__answers`** collapses duplicate responses to one answer per
  (sitting, question). The answer counts as correct only if every copy is
  correct. Responses without a sitting are dropped.
- **`silver__sitting_scores`** computes `p = correct / questions` and the scaled
  score via one macro, `ks2_scaled_score(p)`:
  `least(120, greatest(80, floor(100 + k * (ln(p / (1 - p)) - ln(p_cut / (1 - p_cut))))))`,
  or no score (`N`) if `p < min_p`.

### Gold: sparse type-2 history

One row per (pupil, subject, scored sitting):

| Column | Meaning |
|---|---|
| surrogate key | hash of (`pupil_id`, `subject_id`, `session_id`) |
| `pupil_id`, `subject_id`, `subject_name`, `session_id` | natural key and labels |
| `scaled_score`, `score_status` | null score with status `N` when below the minimum |
| `questions`, `correct`, `p` | the evidence behind the score |
| `valid_from` | this sitting's `finished_at` |
| `valid_to` | the next scored sitting's `finished_at`, or null |
| `is_current` | true on the pupil × subject's latest row |
| `scoring_method` | e.g. `ks2_logit_v1` |

- Score as of T: `valid_from <= T and (valid_to > T or valid_to is null)`.
- Current score: `is_current`.
- N results are rows too: "no score" is that sitting's outcome.
- **Sparse:** a pupil with no scorable sitting in a subject has no rows.
  Consumers left-join from their pupil list.

### Determinism

- Keys are hashes of natural keys (`dbt_utils.generate_surrogate_key`), never
  sequences or random UUIDs. Natural-key columns are kept alongside.
- Every window `order by` ends in a unique tie-break (e.g. `session_id`).
- No `current_timestamp()` in business columns. It is allowed in metadata only.
- Formula constants are dbt vars (`ks2_logit_slope: 7.3`,
  `ks2_logit_p_cut: 0.5`, `ks2_min_p: 0.05`), and every gold row records its
  `scoring_method`.
- Gold's history is **derived** from silver, never appended to. Rebuilding
  always gives the same table.

### Scale (implemented in task 7)

- `silver__answers`: incremental `merge` on (`session_id`, `question_id`),
  partitioned by `date(answered_at)`, clustered by `session_id`, with a
  3-day lookback for late rows.
- `silver__sitting_scores`: partitioned by `date(finished_at)`, clustered by
  `pupil_id`.
- Gold: rebuilt only for the (pupil, subject) pairs touched by changed
  sittings. Because history is derived, a deleted sitting's row disappears and
  the previous row (if any) becomes current again.

### Reference data

`seeds/ks2_scaled_score_conversion.csv` (official 2024-2026 KS2 tables) is
**not** used for scoring. It is used by tests (the formula must stay close to
the official tables) and documents what the formula is calibrated against.

## Consequences

- One gold table serves current scores, full history and as-of queries, and
  loads into the application database as-is.
- Past as-of results can change when source data is corrected or deleted.
  That is intended (e.g. erasure), but "what did the dashboard show on date
  X" can't be answered.
- Treating `is_deleted` pupils as erased is an assumption to confirm with the
  product team.

## Not doing (yet)

- **Knowledge-time history** (what we believed at T): needs load timestamps
  or snapshots of the source tables from now on.
- **A dense pupil × subject view** with explicit `NOT_ASSESSED` rows: until
  there is a use case for it.
- **Adjusting for question difficulty with Atom data**: estimate question
  difficulty from responses and adjust ability before applying the same
  formula, once there is enough data.
