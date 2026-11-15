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
source de_raw ─┬─ silver__sittings        one row per sitting: scoring rules as flags           (table)
               └─ silver__answers         one row per (sitting, question), duplicates collapsed (incremental)
                    └─ silver__sitting_scores  one row per (sitting, subject): scaled score       (incremental)
                            └─ gold__pupil_subject_scores  type-2 history per pupil × subject    (table)
```

- **`silver__sittings`** keeps every sitting, with `is_scorable` and an
  `exclusion_reason`: `deleted`, `incomplete`, `survey`, `adaptive` or
  `year_group_above_6`. Sittings of deleted pupils are dropped
  here, so a deleted pupil disappears from everything downstream, history
  included.
- **`silver__answers`** collapses duplicate responses to one answer per
  (sitting, question). The answer counts as correct only if every copy is
  correct. No sitting or pupil rules are applied here; responses without a
  sitting simply never reach gold.
- **`silver__sitting_scores`** computes, per (sitting, subject),
  `p = correct / questions` and the scaled score via one macro,
  `ks2_scaled_score(correct, questions)`: `floor(80 + 40p)`, or no score (`N`)
  below 5% correct. Why this formula: [ADR 0002](0002-scaled-score-curve.md).
  It applies no sitting or pupil rules either.
- **`gold__pupil_subject_scores`** joins the scores to scorable sittings (which
  also drops deleted pupils) and builds the history.

### Gold: sparse type-2 history

One row per (pupil, subject, scored sitting):

| Column | Meaning |
|---|---|
| surrogate key | hash of (`pupil_id`, `subject_id`, `session_id`) |
| `pupil_id`, `subject_id`, `subject_name`, `session_id` | natural key and labels |
| `scaled_score`, `has_scaled_score` | `has_scaled_score` is false (and `scaled_score` null) when below the minimum (`N`) |
| `questions`, `correct`, `proportion_correct` | the evidence behind the score |
| `meets_expected_standard` | scaled score of 100 or more |
| `assessment_id`, `year_group_at_sitting` | context for consumers (e.g. to caveat younger year groups) |
| `valid_from` | this sitting's `finished_at` |
| `valid_to` | the next scored sitting's `finished_at`, or null |
| `is_current` | true on the pupil × subject's latest row |
| `scoring_method` | e.g. `linear_v1` |

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
- The minimum for a score is a dbt var (`ks2_min_pct: 5`), and every gold row
  records its `scoring_method`.
- Gold's history is **derived** from silver, never appended to. Rebuilding
  always gives the same table.

### Scale and incremental builds

Only the large tables are incremental; everything small is rebuilt in full on
every run, so changes to sittings and pupils (deletes, completions) can never
go stale.

| Model | Rows (at 100m responses) | Build |
|---|---|---|
| `silver__answers` | ~100m | **microbatch** on `answered_at`, one batch per day, reprocessing the last `answers_lookback_days` (3) days and replacing them whole; partitioned by day, clustered by `session_id` |
| `silver__sitting_scores` | ~4m | **incremental merge** on (`session_id`, `subject_id`): re-scores every sitting with an answer inside the lookback, from all of that sitting's answers |
| `silver__sittings` | ~4m | table, rebuilt every run |
| `gold__pupil_subject_scores` | ~4m | table, rebuilt every run (cheap), so the history, `valid_to` and deletes are always consistent |

- **Idempotent:** batches replace whole days, the merge replaces whole
  sittings, and the tables are rebuilt; re-running gives the same result.
- **Late changes:** the raw tables have no updated-at timestamps, so a
  response changed more than `answers_lookback_days` after it was answered is
  only picked up by `dbt build --full-refresh`, which should run on a schedule
  (e.g. weekly) as a backstop. A sitting or pupil change is picked up on the
  next normal run.
- **Raw table partitioning:** each daily batch filters `de_raw.responses` on
  `answered_at`, but that table isn't partitioned, so today every batch scans
  all of it. At 100m+ rows, `de_raw.responses` should be partitioned by
  `date(answered_at)` upstream for the batches to read only their day.
- Measured on the sample: a normal run reprocesses 4 daily batches (about 17
  seconds); a full refresh rebuilds about 380 days of batches (about 5
  minutes). Running twice gives identical tables, and an incremental build
  gives exactly the same tables as a full refresh.

### Reference data

`seeds/ks2_scaled_score_conversion.csv` (official 2024-2026 KS2 tables) is
**not** used for scoring. The reconciliation notebook compares our scores
with it, and it documents what the formula is checked against.

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
