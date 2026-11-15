# Atom SATs scores

dbt models that give every pupil a KS2 SATs-style scaled score (80–120) in every
subject, based on their responses to Atom assessments. Built on BigQuery.

The brief is in [`reference_docs/take_home_task_content.md`](reference_docs/take_home_task_content.md);
the GOV.UK scaled-score guidance is in [`reference_docs/gov_scaled_conversion_tables.md`](reference_docs/gov_scaled_conversion_tables.md).

## Quick start

```sh
gcloud auth application-default login   # dbt `dev` target uses your gcloud credentials
make setup                              # uv sync, dbt deps, install pre-push hook
make build                              # dbt build (models + seeds + tests)
make check                              # all repo checks (also run on pre-push and in CI)
```

Defaults point at project `atom-analytics-candidates`, dataset `owen_cain`.
Override with `DBT_GCP_PROJECT` / `DBT_DATASET`.

## Project layout

Medallion layers, all built into one BigQuery dataset (we can only write to
one), separated by folder and the `<layer>__<entity>` model-name prefix:

| Layer  | Folder           | Contents |
|--------|------------------|----------|
| bronze | `models/bronze/` | The raw `de_raw` tables, declared as dbt sources with data-quality tests. |
| silver | `models/silver/` | Cleaned, conformed data. _TODO_ |
| gold   | `models/gold/`   | The SATs score output. _TODO_ |

## Design decisions

- [`docs/adr/0001-scoring-data-model.md`](docs/adr/0001-scoring-data-model.md):
  data model and point-in-time semantics.
- [`docs/adr/0002-scaled-score-curve.md`](docs/adr/0002-scaled-score-curve.md):
  how % correct becomes a scaled score (the curve).

## What I built

`gold__pupil_subject_scores` (BigQuery `owen_cain`): a KS2-style scaled score
(80-120) for every pupil in every subject they have a scorable sitting in, as a
**type-2 history**, one row per scored sitting.

```sql
-- current scores
select * from owen_cain.gold__pupil_subject_scores where is_current;

-- scores as they stood at time T
select * from owen_cain.gold__pupil_subject_scores
where valid_from <= @t and (valid_to > @t or valid_to is null);
```

## How the pieces fit together

```
de_raw (sources, bronze) ─┬─ silver__sittings        every sitting + is_scorable / exclusion_reason
                          ├─ silver__answers         one answer per (sitting, question), duplicates collapsed
                          └─ silver__sitting_scores  floor(80 + 40 * correct / questions)
                                       └─ gold__pupil_subject_scores  type-2 history per pupil × subject
```

- `macros/ks2_scaled_score.sql`: the scoring formula, in one place; the
  minimum for a score is a dbt var in `dbt_project.yml`.
- `seeds/ks2_scaled_score_conversion.csv`: official KS2 tables (2024-2026),
  used to calibrate and check the formula, not for scoring.
- Notebooks: `01_exploration` (data profiling), `02_conversion_curves`
  (choosing the formula), `03_reconciliation` (compares our scores with the
  official KS2 conversion tables).

## Data quality issues

Evidence for each is in [`notebooks/01_exploration.py`](notebooks/01_exploration.py)
(`uv run marimo edit notebooks/01_exploration.py`).

- **Orphan responses:** 1,433 `responses` rows (56 sessions) reference a
  `session_id` missing from `assessment_sittings`.
- **Duplicate responses:** 2,082 `(session_id, question_id)` pairs have more
  than one row (4,493 rows), all in complete summative fixed-question sittings.
  Copies share `answered_at`, `seconds_taken` and `question_number` but have
  distinct `response_id`s, and in 965 pairs they disagree on `is_correct`.
  The copy count varies by pupil for the same question, so these are not
  multi-mark questions; they sit inside one sitting, so they are not re-sits.
- **`responses.session_type`** is always `MOCK_TEST` and never matches the
  sitting's `session_type`.
- **Late answers:** 1,608 responses have `answered_at` after the sitting's
  `finished_at`, but by at most 1 second (timestamp rounding). Only
  incomplete sittings lack a `finished_at`.
- **Soft deletes:** no pupil or sitting is currently marked `is_deleted`.
- **Year groups:** 25 sittings (entrance exams) are in years 11, 14 and 15.
- **Unused rows:** 61 pupils have no sittings, 79 sittings have no responses,
  and 8,096 of 10,552 questions in `course_hierarchy` have never been answered.

## Assumptions

Scoring follows the KS2 rules in the GOV.UK guidance where they apply.

- **Conversion to the 80-120 scale:** linear rescaling for every subject,
  `floor(80 + 40p)`, where `p` is the proportion of questions correct (0% →
  80, 50% → 100, 100% → 120); no score (`N`) below 5%. It is within about 1.5
  points of the official 2024-2026 KS2 tables on average (evidence in
  [`notebooks/02_conversion_curves.py`](notebooks/02_conversion_curves.py) and
  [ADR 0002](docs/adr/0002-scaled-score-curve.md)). The real tables aren't
  applied directly because an Atom assessment isn't the KS2 paper they were
  calibrated on.
- **Assumes** an Atom assessment is about as hard as a KS2 paper and one
  question is worth one mark. With more data, question difficulty could be
  estimated from Atom responses to adjust for this.
- **Subjects:** every subject with qualifying sittings is scored (English,
  Maths, Screeners, Verbal and Non-Verbal Reasoning). Science has questions
  but no sittings; Wellbeing sittings are all surveys (no right answers).
- **Qualifying sittings:** complete, not deleted, not a survey and not an
  adaptive mock (adaptive difficulty makes % correct incomparable), year group
  1-6. KS2 precedent: a pupil must sit every paper to receive a score.
- **Orphan responses** are excluded: without a sitting we can't apply the rules
  above.
- **Duplicates** are treated as an upstream double-submission bug: one answer
  per (sitting, question), correct only if every copy is correct. Mean %
  correct moves by under 2 points under "any copy correct" instead.
- **No-attempts** count as wrong (0 marks), as an unanswered KS2 question does.
- **Late answers** are kept (they are at most 1 second late).
- **Unit of scoring:** each qualifying sitting is scored on its own (KS2 never
  pools attempts). A pupil's score as of time T is their latest scored sitting
  finished at or before T.
- **Below the minimum raw score** a pupil gets no scaled score (`N`, outcome
  `NS`), as in the GOV.UK guidance; we don't round them up to 80.

## What I would do next

_TODO_

## AI usage

_TODO: link to exported Claude Code chat logs._
