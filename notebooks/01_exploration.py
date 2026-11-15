import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium", app_title="01 - Exploration")


@app.cell
def _():
    import os

    import marimo as mo
    import polars as pl
    import yaml
    from google.cloud import bigquery
    from google.oauth2.credentials import Credentials

    return Credentials, bigquery, mo, os, pl, yaml


@app.cell
def _(mo):
    mo.md(r"""
    # 01 - Exploring `de_raw`

    Profiles the four raw tables and works out which rows can feed a KS2-style
    scaled score. Each section ends with the finding / decision it supports.

    **Auth:** uses gcloud application-default credentials, or a raw OAuth token
    in `CLOUDSDK_AUTH_ACCESS_TOKEN` if set (agent sandbox).
    """)
    return


@app.cell
def _(Credentials, bigquery, os, pl):
    PROJECT = os.environ.get("DBT_GCP_PROJECT", "atom-analytics-candidates")
    RAW = f"`{PROJECT}.de_raw`"

    _token = os.environ.get("CLOUDSDK_AUTH_ACCESS_TOKEN")
    client = bigquery.Client(
        project=PROJECT,
        location="europe-west2",
        credentials=Credentials(_token) if _token else None,
    )

    def q(sql: str) -> pl.DataFrame:
        """Run a BigQuery query and return the result as a Polars DataFrame."""
        result = pl.from_arrow(client.query(sql).to_arrow())
        assert isinstance(result, pl.DataFrame)
        return result

    return RAW, q


@app.cell
def _(mo):
    mo.md(r"""
    ## 0. Data model

    Pupils sit assessments made up of questions; every question belongs to a
    subject through a hierarchy of topics and subtopics.

    | Table | What it holds | Grain / key | Time columns |
    |---|---|---|---|
    | `pupils` | The pupils on the platform. Only an id and a soft-delete flag. | one row per pupil · `pupil_id` | - |
    | `assessment_sittings` | One attempt by a pupil at an assessment: what kind of session it was, the pupil's year group at the time, how many questions it had and whether it was finished. | one row per sitting · `session_id` | `started_at`, `finished_at` |
    | `responses` | The pupil's answer to one question within a sitting: correct or not, skipped or not, time taken. The fact table everything is scored from. | intended one row per question answered · `response_id` (but see §5: duplicates per `(session_id, question_id)`) | `answered_at` |
    | `course_hierarchy` | Places each question in the curriculum: question → atom → subtopic → topic → subject. Denormalised, so every level is a column. | one row per question · `question_id` | - |

    Things that are **not** tables: `assessment_id` (no assessment dimension, so
    we can't see an assessment's intended subject or length beyond
    `total_questions`), and the atom/subtopic/topic levels have ids only, no names.
    """)
    return


@app.cell
def _(mo):
    mo.mermaid("""
    erDiagram
        pupils ||--o{ assessment_sittings : "sits"
        pupils ||--o{ responses : "answers (denormalised pupil_id)"
        assessment_sittings ||--o{ responses : "contains (session_id)"
        course_hierarchy ||--o{ responses : "is answered as (question_id)"

        pupils {
            string pupil_id PK
            bool is_deleted
        }
        assessment_sittings {
            string session_id PK
            string pupil_id FK
            string assessment_id "no table"
            string session_type
            string style
            int year_group_at_sitting
            int total_questions
            bool is_complete
            bool is_deleted
            timestamp started_at
            timestamp finished_at
        }
        responses {
            string response_id PK
            string pupil_id FK
            string session_id FK
            string question_id FK
            string session_type "always MOCK_TEST"
            bool is_correct
            bool is_no_attempt
            int seconds_taken
            int question_number
            timestamp answered_at
        }
        course_hierarchy {
            string question_id PK
            string atom_id
            string subtopic_id
            string topic_id
            string subject_id
            string subject_name
        }
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ### Columns

    Types come from BigQuery's `INFORMATION_SCHEMA`; descriptions come from the
    dbt source definitions in `models/bronze/_de_raw__sources.yml` (one source
    of truth for column docs).
    """)
    return


@app.cell
def _(RAW, mo, pl, q, yaml):
    _sources_yml = mo.notebook_dir().parent / "models/bronze/_de_raw__sources.yml"
    _source = yaml.safe_load(_sources_yml.read_text())["sources"][0]
    _descriptions = pl.DataFrame(
        [
            {
                "table_name": table["name"],
                "column_name": column["name"],
                "description": column.get("description", ""),
            }
            for table in _source["tables"]
            for column in table.get("columns", [])
        ]
    )

    _schema = q(f"""
    select table_name, column_name, data_type, ordinal_position
    from {RAW}.INFORMATION_SCHEMA.COLUMNS
    """)

    _table_order = ["pupils", "assessment_sittings", "responses", "course_hierarchy"]
    _columns = (
        _schema.join(_descriptions, on=["table_name", "column_name"], how="left")
        .with_columns(
            pl.col("table_name")
            .replace_strict(_table_order, list(range(len(_table_order))))
            .alias("_table_order")
        )
        .sort("_table_order", "ordinal_position")
        .select("table_name", "column_name", "data_type", "description")
    )
    _columns
    return


@app.cell
def _(mo):
    mo.md(r"""
    ### Relationships, as they actually hold

    For each join key: how many child rows find their parent, and the
    cardinality seen in the data. `orphan_rows > 0` means the relationship is
    not enforced upstream.

    **Findings:** the only broken link is `responses.session_id` (1,433 orphan
    responses). Every sitting covers exactly one subject. 61 pupils have no
    sittings, 79 sittings have no responses, and most questions in
    `course_hierarchy` have never been answered - the hierarchy is the whole
    question bank, not just what was asked.
    """)
    return


@app.cell
def _(RAW, q):
    q(f"""
    with relationships as (
        select
            'assessment_sittings.pupil_id -> pupils' as relationship,
            count(*) as child_rows,
            countif(p.pupil_id is null) as orphan_rows
        from {RAW}.assessment_sittings as s
        left join {RAW}.pupils as p on s.pupil_id = p.pupil_id

        union all

        select
            'responses.session_id -> assessment_sittings',
            count(*),
            countif(s.session_id is null)
        from {RAW}.responses as r
        left join {RAW}.assessment_sittings as s on r.session_id = s.session_id

        union all

        select
            'responses.pupil_id -> pupils',
            count(*),
            countif(p.pupil_id is null)
        from {RAW}.responses as r
        left join {RAW}.pupils as p on r.pupil_id = p.pupil_id

        union all

        select
            'responses.question_id -> course_hierarchy',
            count(*),
            countif(ch.question_id is null)
        from {RAW}.responses as r
        left join {RAW}.course_hierarchy as ch on r.question_id = ch.question_id

        union all

        select
            'responses.pupil_id = sitting.pupil_id',
            count(*),
            countif(r.pupil_id != s.pupil_id)
        from {RAW}.responses as r
        inner join {RAW}.assessment_sittings as s on r.session_id = s.session_id
    )

    select * from relationships
    """)
    return


@app.cell
def _(RAW, q):
    # Cardinality: how many children each parent has.
    q(f"""
    with sittings_per_pupil as (
        select p.pupil_id, count(s.session_id) as n
        from {RAW}.pupils as p
        left join {RAW}.assessment_sittings as s on p.pupil_id = s.pupil_id
        group by p.pupil_id
    ),

    responses_per_sitting as (
        select s.session_id, count(r.response_id) as n
        from {RAW}.assessment_sittings as s
        left join {RAW}.responses as r on s.session_id = r.session_id
        group by s.session_id
    ),

    responses_per_question as (
        select ch.question_id, count(r.response_id) as n
        from {RAW}.course_hierarchy as ch
        left join {RAW}.responses as r on ch.question_id = r.question_id
        group by ch.question_id
    ),

    subjects_per_sitting as (
        select r.session_id, count(distinct ch.subject_id) as n
        from {RAW}.responses as r
        inner join {RAW}.course_hierarchy as ch on r.question_id = ch.question_id
        group by r.session_id
    )

    select
        'sittings per pupil' as measure,
        countif(n = 0) as parents_with_none,
        min(n) as min_n,
        approx_quantiles(n, 2)[offset(1)] as median_n,
        max(n) as max_n
    from sittings_per_pupil
    union all
    select 'responses per sitting', countif(n = 0), min(n), approx_quantiles(n, 2)[offset(1)], max(n)
    from responses_per_sitting
    union all
    select 'responses per question', countif(n = 0), min(n), approx_quantiles(n, 2)[offset(1)], max(n)
    from responses_per_question
    union all
    select 'subjects per sitting', countif(n = 0), min(n), approx_quantiles(n, 2)[offset(1)], max(n)
    from subjects_per_sitting
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 1. Table sizes
    """)
    return


@app.cell
def _(RAW, q):
    q(f"""
    select 'pupils' as table_name, count(*) as row_count from {RAW}.pupils
    union all select 'assessment_sittings', count(*) from {RAW}.assessment_sittings
    union all select 'responses', count(*) from {RAW}.responses
    union all select 'course_hierarchy', count(*) from {RAW}.course_hierarchy
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 2. Subjects (`course_hierarchy`)

    KS2 only awards scaled scores for **reading**, **grammar, punctuation &
    spelling (GPS)** and **maths**. Science is teacher-assessed only; verbal /
    non-verbal reasoning are not national-curriculum subjects.

    **Decision:** score every subject that has qualifying sittings, with one
    KS2-style formula for all of them, since an Atom assessment isn't a KS2
    paper anyway (see `02_conversion_curves` and ADR 0002). Wellbeing drops
    out because its sittings are all surveys.
    """)
    return


@app.cell
def _(RAW, q):
    q(f"""
    select
        subject_name,
        count(*) as questions,
        count(distinct topic_id) as topics,
        count(distinct subtopic_id) as subtopics
    from {RAW}.course_hierarchy
    group by subject_name
    order by questions desc
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 3. Sittings (`assessment_sittings`)

    **Findings:** no sitting is soft-deleted; surveys are the Wellbeing
    sittings; adaptive mocks vary difficulty per pupil so their % correct isn't
    comparable; entrance exams include year groups > 6.

    **Decision:** score only complete, non-deleted, non-survey, non-adaptive
    sittings (KS2 precedent: a pupil must sit every paper to get a score).
    """)
    return


@app.cell
def _(RAW, q):
    q(f"""
    select
        session_type,
        style,
        count(*) as sittings,
        countif(is_complete) as complete,
        countif(is_deleted) as deleted,
        countif(finished_at is null) as no_finished_at,
        count(distinct assessment_id) as assessments,
        min(year_group_at_sitting) as min_year_group,
        max(year_group_at_sitting) as max_year_group,
        min(total_questions) as min_questions,
        max(total_questions) as max_questions,
        min(started_at) as first_started,
        max(started_at) as last_started
    from {RAW}.assessment_sittings
    group by session_type, style
    order by sittings desc
    """)
    return


@app.cell
def _(RAW, q):
    q(f"""
    select
        year_group_at_sitting,
        session_type,
        count(*) as sittings
    from {RAW}.assessment_sittings
    group by year_group_at_sitting, session_type
    order by year_group_at_sitting, session_type
    """)
    return


@app.cell
def _(RAW, q):
    q(f"""
    select
        s.session_type,
        s.style,
        ch.subject_name,
        count(distinct s.session_id) as sittings
    from {RAW}.assessment_sittings as s
    inner join {RAW}.responses as r on s.session_id = r.session_id
    inner join {RAW}.course_hierarchy as ch on r.question_id = ch.question_id
    group by s.session_type, s.style, ch.subject_name
    order by s.session_type, s.style, sittings desc
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 4. Responses

    **Findings:**
    - `responses.session_type` is always `MOCK_TEST` and never matches the
      sitting's type, so it is ignored in favour of the sitting's.
    - Some responses reference a `session_id` with no sitting ("orphans"). We
      can't check completeness / type / year group for them, so they're excluded.
    - Some responses are answered after the sitting's `finished_at`, but by at
      most 1 second (timestamp rounding), so they're kept.
    """)
    return


@app.cell
def _(RAW, q):
    q(f"""
    select
        r.session_type as response_session_type,
        s.session_id is null as is_orphan,
        count(*) as responses,
        count(distinct r.session_id) as sessions,
        count(distinct r.pupil_id) as pupils,
        countif(r.is_correct) as correct,
        countif(r.is_no_attempt) as no_attempt,
        countif(r.is_no_attempt and r.is_correct) as no_attempt_but_correct,
        countif(r.answered_at > s.finished_at) as answered_after_finish,
        countif(r.answered_at < s.started_at) as answered_before_start,
        countif(r.pupil_id != s.pupil_id) as pupil_mismatch
    from {RAW}.responses as r
    left join {RAW}.assessment_sittings as s on r.session_id = s.session_id
    group by response_session_type, is_orphan
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 5. Duplicate responses

    A "duplicate" = more than one row for the same `(session_id, question_id)`.

    **Findings:**
    - Every copy has its own `response_id` but identical `answered_at`,
      `seconds_taken` and `question_number`, so there is no ordering to pick a
      "latest" answer.
    - Copies often disagree on `is_correct`.
    - Not multi-mark questions: the same question has a different number of
      copies for different pupils (table 5c).
    - Not re-sits: all copies sit inside one sitting (re-sits are section 6).

    **Assumption:** an upstream double-submission / ingestion bug. Collapse to
    one row per (sitting, question); count as correct only if **all** copies are
    correct (conservative). Section 8 shows how much this choice matters.
    """)
    return


@app.cell
def _(RAW, q):
    q(f"""
    with duplicate_answers as (
        select
            session_id,
            question_id,
            count(*) as copies,
            count(distinct response_id) as distinct_ids,
            count(distinct is_correct) as correct_values,
            count(distinct answered_at) as distinct_answered_at,
            count(distinct seconds_taken) as distinct_seconds,
            count(distinct question_number) as distinct_question_numbers
        from {RAW}.responses
        group by session_id, question_id
        having count(*) > 1
    )

    select
        copies,
        correct_values > 1 as copies_disagree,
        countif(distinct_ids = copies) as all_ids_distinct,
        countif(distinct_answered_at > 1) as differing_timestamps,
        countif(distinct_seconds > 1) as differing_seconds,
        countif(distinct_question_numbers > 1) as differing_question_numbers,
        count(*) as duplicate_groups
    from duplicate_answers
    group by copies, copies_disagree
    order by copies, copies_disagree
    """)
    return


@app.cell
def _(RAW, q):
    q(f"""
    with per_sitting as (
        select
            r.session_id,
            count(distinct r.question_id) as distinct_questions,
            count(*) as response_rows,
            count(distinct r.question_id) != count(*) as has_duplicates
        from {RAW}.responses as r
        group by r.session_id
    )

    select
        coalesce(s.session_type, '(orphan)') as session_type,
        coalesce(s.style, '(orphan)') as style,
        count(*) as sittings,
        countif(p.has_duplicates) as sittings_with_duplicates,
        countif(p.distinct_questions = s.total_questions) as distinct_eq_total,
        countif(p.distinct_questions < s.total_questions) as distinct_lt_total,
        countif(p.distinct_questions > s.total_questions) as distinct_gt_total
    from per_sitting as p
    left join {RAW}.assessment_sittings as s on p.session_id = s.session_id
    group by session_type, style
    order by sittings desc
    """)
    return


@app.cell
def _(RAW, q):
    # 5c: if duplicates were multi-mark parts, a question would always have the
    # same number of rows. It doesn't.
    q(f"""
    with copies as (
        select question_id, session_id, count(*) as n
        from {RAW}.responses
        group by question_id, session_id
    )

    select
        question_id,
        count(*) as sittings,
        countif(n > 1) as sittings_with_copies,
        array_agg(distinct n order by n) as copy_counts_seen
    from copies
    group by question_id
    having max(n) > 1
    order by sittings desc
    limit 15
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 6. Re-sits

    KS2 has no re-sits (only a timetable variation of up to 5 school days, and
    missing any paper means no score). In Atom data a pupil can sit the same
    assessment more than once, but it's rare.

    **Decision:** score every qualifying sitting; a pupil's subject score as of
    time T is their **latest** scored sitting finished at or before T.
    """)
    return


@app.cell
def _(RAW, q):
    q(f"""
    with counts as (
        select pupil_id, assessment_id, count(*) as sittings
        from {RAW}.assessment_sittings
        group by pupil_id, assessment_id
    )

    select sittings as sittings_of_same_assessment, count(*) as pupil_assessments
    from counts
    group by sittings
    order by sittings
    """)
    return


@app.cell
def _(RAW, q):
    q(f"""
    with ordered as (
        select
            pupil_id,
            assessment_id,
            session_id,
            is_complete,
            started_at,
            finished_at,
            count(*) over (partition by pupil_id, assessment_id) as attempts,
            row_number() over (
                partition by pupil_id, assessment_id order by started_at
            ) as attempt_number
        from {RAW}.assessment_sittings
    )

    select * except (attempts)
    from ordered
    where attempts > 1
    order by pupil_id, assessment_id, attempt_number
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 7. Qualifying-data funnel

    Applies the agreed rules one at a time to show what each removes.
    """)
    return


@app.cell
def _(RAW, q):
    q(f"""
    with base as (
        select
            r.session_id,
            r.question_id,
            s.session_id is not null as has_sitting,
            coalesce(not s.is_deleted, false) as not_deleted,
            coalesce(s.is_complete, false) as is_complete,
            coalesce(s.style not in ('survey', 'adaptive'), false) as fixed_form,
            coalesce(s.year_group_at_sitting <= 6, false) as primary_year
        from {RAW}.responses as r
        left join {RAW}.assessment_sittings as s on r.session_id = s.session_id
    ),

    steps as (
        select 0 as step, 'all responses' as rule, * from base
        union all select 1, '+ has a sitting', * from base where has_sitting
        union all select 2, '+ not deleted', * from base where has_sitting and not_deleted
        union all select 3, '+ complete', * from base
            where has_sitting and not_deleted and is_complete
        union all select 4, '+ not survey / adaptive', * from base
            where has_sitting and not_deleted and is_complete and fixed_form
        union all select 5, '+ year group <= 6', * from base
            where has_sitting and not_deleted and is_complete and fixed_form and primary_year
    )

    select
        step,
        rule,
        count(*) as response_rows,
        count(distinct format('%s|%s', session_id, question_id)) as distinct_answers,
        count(distinct session_id) as sittings
    from steps
    group by step, rule
    order by step
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 8. % correct per qualifying sitting, and duplicate sensitivity

    Per qualifying sitting: % correct (no-attempts count as wrong) under three
    duplicate-handling rules:
    - `all_copies` (chosen): correct only if every copy is correct
    - `any_copy`: correct if any copy is correct
    - `drop_conflicts`: drop questions whose copies disagree
    """)
    return


@app.cell
def _(RAW, q):
    pct = q(f"""
    with qualifying_sittings as (
        select session_id, pupil_id, year_group_at_sitting
        from {RAW}.assessment_sittings
        where
            is_complete
            and not is_deleted
            and style not in ('survey', 'adaptive')
            and year_group_at_sitting <= 6
    ),

    answers as (
        select
            r.session_id,
            r.question_id,
            ch.subject_name,
            logical_and(r.is_correct) as all_copies,
            logical_or(r.is_correct) as any_copy,
            count(distinct r.is_correct) > 1 as conflicting
        from {RAW}.responses as r
        inner join qualifying_sittings as s on r.session_id = s.session_id
        inner join {RAW}.course_hierarchy as ch on r.question_id = ch.question_id
        group by r.session_id, r.question_id, ch.subject_name
    )

    select
        a.session_id,
        any_value(s.pupil_id) as pupil_id,
        any_value(s.year_group_at_sitting) as year_group,
        a.subject_name,
        count(*) as questions,
        countif(a.conflicting) as conflicting_questions,
        round(100 * countif(a.all_copies) / count(*), 1) as pct_all_copies,
        round(100 * countif(a.any_copy) / count(*), 1) as pct_any_copy,
        round(
            100 * countif(a.all_copies and not a.conflicting)
            / nullif(countif(not a.conflicting), 0),
            1
        ) as pct_drop_conflicts
    from answers as a
    inner join qualifying_sittings as s on a.session_id = s.session_id
    group by a.session_id, a.subject_name
    """)
    pct
    return (pct,)


@app.cell
def _(pct, pl):
    pct.group_by("subject_name").agg(
        pl.len().alias("sittings"),
        pl.col("questions").median().alias("median_questions"),
        pl.col("pct_all_copies").mean().round(1).alias("mean_pct_all_copies"),
        pl.col("pct_any_copy").mean().round(1).alias("mean_pct_any_copy"),
        pl.col("pct_drop_conflicts").mean().round(1).alias("mean_pct_drop_conflicts"),
        (pl.col("pct_any_copy") - pl.col("pct_all_copies"))
        .max()
        .alias("max_gap_any_vs_all"),
        (pl.col("conflicting_questions") > 0).sum().alias("sittings_with_conflicts"),
    ).sort("subject_name")
    return


@app.cell
def _(pct, pl):
    # Distribution of % correct (chosen rule) in 10-point buckets.
    (
        pct.with_columns(
            (pl.col("pct_all_copies") // 10 * 10).cast(pl.Int64).alias("pct_bucket")
        )
        .group_by("subject_name", "pct_bucket")
        .len()
        .sort("subject_name", "pct_bucket")
        .pivot(on="subject_name", index="pct_bucket", values="len")
        .fill_null(0)
    )
    return


@app.cell
def _(pct, pl):
    # Sittings per year group: how many scores would be for younger pupils.
    pct.group_by("year_group", "subject_name").len().pivot(
        on="subject_name", index="year_group", values="len"
    ).sort("year_group").fill_null(0)
    return


if __name__ == "__main__":
    app.run()
