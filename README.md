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

- 1,433 `responses` rows reference a `session_id` that is missing from
  `assessment_sittings` (source relationship test, `warn`). _TODO: investigate._

## Assumptions

_TODO_

## What I would do next

_TODO_

## AI usage

_TODO: link to exported Claude Code chat logs._
