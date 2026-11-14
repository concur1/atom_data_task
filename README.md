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

## What I built

_TODO_

## How the pieces fit together

_TODO_

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
  `finished_at`; 31 sittings have no `finished_at`.
- **Soft deletes:** no pupil or sitting is currently marked `is_deleted`.
- **Year groups:** 25 sittings (entrance exams) are in years 11, 14 and 15.
- **Unused rows:** 61 pupils have no sittings, 79 sittings have no responses,
  and 8,096 of 10,552 questions in `course_hierarchy` have never been answered.

## Assumptions

Scoring follows the KS2 rules in the GOV.UK guidance where they apply.

- **Subjects:** KS2 awards scaled scores only for reading, GPS and maths.
  Maths is scored with the KS2 maths table and English with the KS2 reading
  table (Atom's English topics aren't labelled reading vs GPS). Science,
  Verbal/Non-Verbal Reasoning, Screeners and Wellbeing have no KS2 scaled-score
  equivalent and are not scored, rather than given a misleading proxy.
- **Qualifying sittings:** complete, not deleted, not a survey and not an
  adaptive mock (adaptive difficulty makes % correct incomparable), year group
  1-6. KS2 precedent: a pupil must sit every paper to receive a score.
- **Orphan responses** are excluded: without a sitting we can't apply the rules
  above.
- **Duplicates** are treated as an upstream double-submission bug: one answer
  per (sitting, question), correct only if every copy is correct. Mean %
  correct moves by under 2 points under "any copy correct" instead.
- **No-attempts** count as wrong (0 marks), as an unanswered KS2 question does.
- **Late answers** are kept (likely sync lag).
- **Unit of scoring:** each qualifying sitting is scored on its own (KS2 never
  pools attempts). A pupil's score as of time T is their latest scored sitting
  finished at or before T.
- **Below the minimum raw score** a pupil gets no scaled score (`N`, outcome
  `NS`), as in the GOV.UK guidance; we don't round them up to 80.

## What I would do next

_TODO_

## AI usage

_TODO: link to exported Claude Code chat logs._
