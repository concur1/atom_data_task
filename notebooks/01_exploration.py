import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium", app_title="01 - Exploration")


@app.cell
def _():
    import os

    import marimo as mo
    import polars as pl
    from google.cloud import bigquery
    from google.oauth2.credentials import Credentials

    return Credentials, bigquery, mo, os, pl


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

    **Decision:** score Maths (KS2 maths table) and English (KS2 reading table).
    Other subjects get no score rather than a made-up proxy.
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
    - Some responses are answered after the sitting's `finished_at`. Kept
      (likely sync lag) but worth flagging.
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
            coalesce(s.year_group_at_sitting <= 6, false) as primary_year,
            ch.subject_name in ('English', 'Maths') as ks2_subject
        from {RAW}.responses as r
        left join {RAW}.assessment_sittings as s on r.session_id = s.session_id
        left join {RAW}.course_hierarchy as ch on r.question_id = ch.question_id
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
        union all select 6, '+ English / Maths', * from base
            where has_sitting and not_deleted and is_complete and fixed_form and primary_year
            and ks2_subject
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
        where ch.subject_name in ('English', 'Maths')
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


@app.cell
def _(mo):
    mo.md(r"""
    ## 9. Next: conversion tables

    Still to add in this task: GOV.UK raw → scaled conversion tables (reading
    and maths) for the latest year plus two earlier years, to compare how much
    the choice of year moves scores.
    """)
    return


if __name__ == "__main__":
    app.run()
