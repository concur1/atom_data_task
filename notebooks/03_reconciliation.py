import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium", app_title="03 - Reconciliation")


@app.cell
def _():
    import os
    import subprocess

    import altair as alt
    import marimo as mo
    import numpy as np
    import polars as pl
    from google.cloud import bigquery
    from google.oauth2.credentials import Credentials

    return Credentials, alt, bigquery, mo, np, os, pl, subprocess


@app.cell
def _(mo):
    mo.md(r"""
    # 03 - Reconciling `gold__pupil_subject_scores`

    Checks that the dbt pipeline (`de_raw` → silver → gold) does what the ADR
    (`docs/adr/0001-scoring-data-model.md`) says: every input row is accounted
    for, keys are unique, nothing unexpected is null, the point-in-time history
    is well formed, scores match an independent recalculation, re-running
    changes nothing, and our curve behaves like the official KS2 curves.

    **Auth:** gcloud application-default credentials, or a raw OAuth token in
    `CLOUDSDK_AUTH_ACCESS_TOKEN`.
    """)
    return


@app.cell
def _(Credentials, bigquery, os, pl):
    PROJECT = os.environ.get("DBT_GCP_PROJECT", "atom-analytics-candidates")
    DATASET = os.environ.get("DBT_DATASET", "owen_cain")
    RAW = f"`{PROJECT}.de_raw`"
    OUT = f"`{PROJECT}.{DATASET}`"

    _token = os.environ.get("CLOUDSDK_AUTH_ACCESS_TOKEN")
    _client = bigquery.Client(
        project=PROJECT,
        location="europe-west2",
        credentials=Credentials(_token) if _token else None,
    )

    def q(sql: str) -> pl.DataFrame:
        """Run a BigQuery query and return the result as a Polars DataFrame."""
        result = pl.from_arrow(_client.query(sql).to_arrow())
        assert isinstance(result, pl.DataFrame)
        return result

    def fingerprint() -> pl.DataFrame:
        """Order-independent content hash of every pipeline output."""
        return pl.concat(
            q(f"""
            select
                '{model}' as model,
                count(*) as row_count,
                bit_xor(farm_fingerprint(to_json_string(t))) as content_hash
            from {OUT}.{model} as t
            """)
            for model in [
                "silver__sittings",
                "silver__answers",
                "silver__sitting_scores",
                "gold__pupil_subject_scores",
            ]
        )

    return OUT, RAW, fingerprint, q


@app.cell
def _(mo):
    mo.md(r"""
    ## 1. Run the pipeline (and check it's idempotent)

    Fingerprints every output, runs `dbt build` (models, seeds and tests),
    then fingerprints again. **Re-runnable** means the two fingerprints match
    whenever the inputs haven't changed. Press the button to run.
    """)
    return


@app.cell
def _(mo):
    run_button = mo.ui.run_button(label="Run dbt build")
    run_button
    return (run_button,)


@app.cell
def _(fingerprint, mo, pl, run_button, subprocess):
    mo.stop(
        not run_button.value, mo.md("_Press **Run dbt build** to run the pipeline._")
    )

    _before = fingerprint()
    _result = subprocess.run(
        ["uv", "run", "dbt", "build"],
        cwd=mo.notebook_dir().parent,
        capture_output=True,
        text=True,
    )
    _after = fingerprint()
    idempotency = _before.join(_after, on="model", suffix="_after").with_columns(
        unchanged=(pl.col("content_hash") == pl.col("content_hash_after"))
        & (pl.col("row_count") == pl.col("row_count_after"))
    )
    mo.vstack(
        [
            mo.md(f"`dbt build` exit code: **{_result.returncode}**"),
            mo.accordion({"dbt output": mo.plain_text(_result.stdout[-6000:])}),
            idempotency,
        ]
    )
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 2. Row counts: where every input row goes

    Each stage's rows, and why rows leave between stages.
    """)
    return


@app.cell
def _(OUT, RAW, q):
    q(f"""
    select 1 as step, 'de_raw.responses' as stage, count(*) as row_count,
        'raw response rows' as grain
    from {RAW}.responses
    union all
    select 2, 'silver__answers', count(*), 'one per (sitting, question)'
    from {OUT}.silver__answers
    union all
    select 3, 'de_raw.assessment_sittings', count(*), 'raw sittings'
    from {RAW}.assessment_sittings
    union all
    select 4, 'silver__sittings', count(*), 'sittings of non-deleted pupils'
    from {OUT}.silver__sittings
    union all
    select 5, 'silver__sittings (scorable)', countif(is_scorable), 'sittings that get a score'
    from {OUT}.silver__sittings
    union all
    select 6, 'silver__sitting_scores', count(*), 'one per (scorable sitting, subject)'
    from {OUT}.silver__sitting_scores
    union all
    select 7, 'gold__pupil_subject_scores', count(*), 'one per (pupil, subject, scored sitting)'
    from {OUT}.gold__pupil_subject_scores
    order by step
    """)
    return


@app.cell
def _(OUT, RAW, q):
    # Responses: raw rows = answers' collapsed copies + orphans (no sitting).
    q(f"""
    select
        (select count(*) from {RAW}.responses) as raw_response_rows,
        (select sum(response_copies) from {OUT}.silver__answers) as rows_in_answers,
        (select sum(response_copies) - count(*) from {OUT}.silver__answers)
            as duplicate_copies_collapsed,
        (
            select count(*)
            from {RAW}.responses as r
            left join {OUT}.silver__sittings as s on r.session_id = s.session_id
            where s.session_id is null
        ) as orphan_rows_dropped,
        (select count(*) from {RAW}.responses)
        - (select sum(response_copies) from {OUT}.silver__answers)
        - (
            select count(*)
            from {RAW}.responses as r
            left join {OUT}.silver__sittings as s on r.session_id = s.session_id
            where s.session_id is null
        ) as unexplained_rows
    """)
    return


@app.cell
def _(OUT, q):
    q(f"""
    select
        coalesce(exclusion_reason, '(scorable)') as exclusion_reason,
        count(*) as sittings,
        sum(response_rows) as response_rows
    from {OUT}.silver__sittings
    group by exclusion_reason
    order by sittings desc
    """)
    return


@app.cell
def _(OUT, q):
    # Scorable sittings that produced no score row (should be none) and
    # scored sittings that aren't in gold (should be none).
    q(f"""
    select
        (
            select count(*)
            from {OUT}.silver__sittings as s
            left join {OUT}.silver__sitting_scores as sc on s.session_id = sc.session_id
            where s.is_scorable and sc.session_id is null
        ) as scorable_sittings_without_score,
        (
            select count(*)
            from {OUT}.silver__sitting_scores as sc
            left join {OUT}.gold__pupil_subject_scores as g
                on sc.session_id = g.session_id and sc.subject_id = g.subject_id
            where g.session_id is null
        ) as scores_missing_from_gold
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 3. Before / after: what the de-duplication changed

    Per scored sitting, % correct from raw rows (every copy counted) vs from
    `silver__answers` (one answer per question).
    """)
    return


@app.cell
def _(OUT, RAW, q):
    q(f"""
    with raw_pct as (
        select session_id, countif(is_correct) / count(*) as raw_p
        from {RAW}.responses
        group by session_id
    )

    select
        g.subject_name,
        count(*) as scored_sittings,
        countif(abs(g.proportion_correct - r.raw_p) > 1e-9) as sittings_changed,
        round(100 * avg(r.raw_p), 2) as mean_pct_raw_rows,
        round(100 * avg(g.proportion_correct), 2) as mean_pct_after_dedup,
        round(100 * max(abs(g.proportion_correct - r.raw_p)), 1) as max_change_pct_points
    from {OUT}.gold__pupil_subject_scores as g
    inner join raw_pct as r on g.session_id = r.session_id
    group by g.subject_name
    order by scored_sittings desc
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 4. Duplicates

    Keys that must be unique: the surrogate key, the natural key, and the
    silver grains.
    """)
    return


@app.cell
def _(OUT, q):
    q(f"""
    select 'gold: pupil_subject_score_id' as key_checked,
        count(*) - count(distinct pupil_subject_score_id) as duplicates
    from {OUT}.gold__pupil_subject_scores
    union all
    select 'gold: (pupil_id, subject_id, session_id)',
        count(*) - count(distinct format('%s|%s|%s', pupil_id, subject_id, session_id))
    from {OUT}.gold__pupil_subject_scores
    union all
    select 'silver__answers: (session_id, question_id)',
        count(*) - count(distinct format('%s|%s', session_id, question_id))
    from {OUT}.silver__answers
    union all
    select 'silver__sittings: session_id',
        count(*) - count(distinct session_id)
    from {OUT}.silver__sittings
    union all
    select 'silver__sitting_scores: (session_id, subject_id)',
        count(*) - count(distinct format('%s|%s', session_id, subject_id))
    from {OUT}.silver__sitting_scores
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 5. Nulls

    Null counts per gold column. Expected nulls: `scaled_score` exactly where
    `has_scaled_score` is false, and `valid_to` exactly where `is_current`.
    """)
    return


@app.cell
def _(OUT, pl, q):
    _cols = q(f"""
    select column_name
    from {OUT}.INFORMATION_SCHEMA.COLUMNS
    where table_name = 'gold__pupil_subject_scores'
    order by ordinal_position
    """)["column_name"].to_list()
    _nulls = q(
        "select "
        + ", ".join(f"countif({c} is null) as {c}" for c in _cols)
        + f" from {OUT}.gold__pupil_subject_scores"
    )
    _expected = q(f"""
    select
        countif((scaled_score is null) = has_scaled_score) as scaled_score_null_mismatch,
        countif((valid_to is null) != is_current) as valid_to_null_mismatch
    from {OUT}.gold__pupil_subject_scores
    """)
    pl.concat(
        [
            _nulls.unpivot(variable_name="column", value_name="null_count"),
            _expected.unpivot(variable_name="column", value_name="null_count"),
        ]
    )
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 6. Gaps in the input data

    - **Calendar gaps:** days between the first and last response with no
      responses at all (weekends/holidays are expected).
    - **Question gaps:** scored sittings with fewer answered questions than the
      sitting's `total_questions`, or holes in the `question_number` sequence.
    """)
    return


@app.cell
def _(RAW, alt, mo, q):
    _daily = q(f"""
    with days as (
        select day
        from unnest(generate_date_array(
            (select min(date(answered_at)) from {RAW}.responses),
            (select max(date(answered_at)) from {RAW}.responses)
        )) as day
    ),

    counts as (
        select date(answered_at) as day, count(*) as responses
        from {RAW}.responses
        group by day
    )

    select
        days.day,
        format_date('%A', days.day) as weekday,
        coalesce(counts.responses, 0) as responses
    from days
    left join counts on days.day = counts.day
    order by days.day
    """)
    _gaps = _daily.filter(_daily["responses"] == 0)
    mo.vstack(
        [
            mo.md(
                f"{_daily.height} days from {_daily['day'].min()} to "
                f"{_daily['day'].max()}; **{_gaps.height} days with no responses** "
                f"({(_gaps['weekday'].is_in(['Saturday', 'Sunday'])).sum()} of them weekends)."
            ),
            mo.ui.altair_chart(
                alt.Chart(_daily)
                .mark_bar()
                .encode(
                    x="day:T",
                    y="responses:Q",
                    tooltip=["day:T", "weekday", "responses"],
                )
                .properties(width=700, height=180, title="Responses per day")
            ),
        ]
    )
    return


@app.cell
def _(OUT, q):
    q(f"""
    with per_sitting as (
        select
            a.session_id,
            count(*) as answered,
            min(a.question_number) as min_number,
            max(a.question_number) as max_number
        from {OUT}.silver__answers as a
        group by a.session_id
    )

    select
        count(*) as scored_sittings,
        countif(p.answered < s.total_questions) as fewer_answers_than_total_questions,
        countif(p.max_number - p.min_number + 1 != p.answered) as question_number_holes,
        countif(p.min_number != 1) as not_starting_at_question_1
    from {OUT}.gold__pupil_subject_scores as g
    inner join per_sitting as p on g.session_id = p.session_id
    inner join {OUT}.silver__sittings as s on g.session_id = s.session_id
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 7. Point-in-time history

    For each (pupil, subject): exactly one current row, intervals that chain
    without overlaps or holes (`valid_to` = next row's `valid_from`), and
    `valid_from < valid_to`.
    """)
    return


@app.cell
def _(OUT, q):
    q(f"""
    with ordered as (
        select
            *,
            lead(valid_from) over (
                partition by pupil_id, subject_id order by valid_from, session_id
            ) as next_valid_from
        from {OUT}.gold__pupil_subject_scores
    ),

    per_pair as (
        select pupil_id, subject_id, countif(is_current) as current_rows
        from {OUT}.gold__pupil_subject_scores
        group by pupil_id, subject_id
    )

    select
        (select count(*) from per_pair) as pupil_subject_pairs,
        (select countif(current_rows != 1) from per_pair) as pairs_without_exactly_one_current,
        countif(valid_to is distinct from next_valid_from) as broken_chain_links,
        countif(valid_to <= valid_from) as zero_or_negative_intervals
    from ordered
    """)
    return


@app.cell
def _(OUT, mo, q):
    _pick = q(f"""
    select pupil_id, subject_name
    from {OUT}.gold__pupil_subject_scores
    group by pupil_id, subject_name
    order by count(*) desc, pupil_id, subject_name
    limit 1
    """).row(0)
    _pupil, _subject = _pick
    _history = q(f"""
    select session_id, valid_from, valid_to, is_current, scaled_score, has_scaled_score
    from {OUT}.gold__pupil_subject_scores
    where pupil_id = '{_pupil}' and subject_name = '{_subject}'
    order by valid_from
    """)
    _as_of = q(f"""
    with checkpoints as (
        select ts
        from unnest(generate_timestamp_array(
            (select min(valid_from) from {OUT}.gold__pupil_subject_scores
             where pupil_id = '{_pupil}' and subject_name = '{_subject}'),
            (select max(valid_from) from {OUT}.gold__pupil_subject_scores
             where pupil_id = '{_pupil}' and subject_name = '{_subject}'),
            interval 7 day
        )) as ts
    )

    select
        c.ts as as_of,
        count(g.session_id) as rows_matched,
        any_value(g.scaled_score) as scaled_score_as_of
    from checkpoints as c
    left join {OUT}.gold__pupil_subject_scores as g
        on g.pupil_id = '{_pupil}'
        and g.subject_name = '{_subject}'
        and g.valid_from <= c.ts
        and (g.valid_to > c.ts or g.valid_to is null)
    group by c.ts
    order by c.ts
    """)
    mo.vstack(
        [
            mo.md(
                f"Example: pupil `{_pupil}`, {_subject}. History, then the as-of "
                "query run weekly (each checkpoint must match exactly one row)."
            ),
            _history,
            _as_of,
        ]
    )
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 8. Independent recalculation of every score

    Recompute every gold score in Python from `correct` and `questions` with
    the formula in the ADR (not the dbt macro), and compare.
    """)
    return


@app.cell
def _(OUT, np, pl, q):
    MIN_PCT = 5

    def formula(correct: np.ndarray, total: np.ndarray) -> np.ndarray:
        """ADR 0002: floor(80 + 40 * correct / total); NaN = N (below MIN_PCT %)."""
        correct = np.asarray(correct, dtype=np.int64)
        total = np.asarray(total, dtype=np.int64)
        score = (80 + (40 * correct) // total).astype(float)
        return np.where(correct * 100 < MIN_PCT * total, np.nan, score)

    gold = q(f"select * from {OUT}.gold__pupil_subject_scores")
    recalculated = gold.with_columns(
        recomputed=pl.Series(
            formula(gold["correct"].to_numpy(), gold["questions"].to_numpy())
        )
        .fill_nan(None)
        .cast(pl.Int64)
    )
    recalculated.select(
        rows=pl.len(),
        mismatches=(
            (pl.col("recomputed") != pl.col("scaled_score"))
            | (pl.col("recomputed").is_null() != pl.col("scaled_score").is_null())
        ).sum(),
        proportion_mismatches=(
            (
                pl.col("proportion_correct") - pl.col("correct") / pl.col("questions")
            ).abs()
            > 1e-12
        ).sum(),
        out_of_range=(~pl.col("scaled_score").is_between(80, 120)).sum(),
    )
    return formula, gold


@app.cell
def _(mo):
    mo.md(r"""
    ## 9. Our curve vs the KS2 curves

    The official 2024-2026 KS2 conversion tables (the `ks2_scaled_score_conversion`
    seed, plotted as % of available marks) against our linear rescaling
    (`80 + 40p`, ADR 0002),
    with every scored Atom sitting overlaid.
    """)
    return


@app.cell
def _(OUT, alt, formula, gold, mo, np, pl, q):
    _max_marks = {"reading": 50, "maths": 110, "gps": 70}
    _ks2 = (
        q(
            f"select * from {OUT}.ks2_scaled_score_conversion where scaled_score is not null"
        )
        .with_columns(
            pct=100
            * pl.col("raw_score")
            / pl.col("ks2_subject").replace_strict(_max_marks, return_dtype=pl.Int64),
            curve=pl.format("KS2 {} {}", pl.col("ks2_subject"), pl.col("test_year")),
        )
        .select("pct", "scaled_score", "curve")
    )
    _steps = np.arange(401)  # 0.25% steps: correct = 0..400 out of 400
    _ours = pl.DataFrame(
        {
            "pct": _steps / 4,
            "scaled_score": formula(_steps, np.full(401, 400)),
            "curve": "Atom (linear 80 + 40p)",
        }
    ).filter(pl.col("scaled_score").is_not_nan())
    _points = gold.drop_nulls("scaled_score").select(
        pct=100 * pl.col("proportion_correct"),
        scaled_score="scaled_score",
        subject="subject_name",
    )

    _x = alt.X(
        "pct:Q",
        title="% correct / % of available marks",
        scale=alt.Scale(domain=[0, 100]),
    )
    _y = alt.Y(
        "scaled_score:Q", title="Scaled score", scale=alt.Scale(domain=[78, 122])
    )
    _ks2_lines = (
        alt.Chart(_ks2)
        .mark_line(interpolate="step-after", opacity=0.45, strokeWidth=1.2)
        .encode(x=_x, y=_y, color=alt.Color("curve:N", title="Curve"))
    )
    _our_line = (
        alt.Chart(_ours)
        .mark_line(color="black", strokeWidth=3)
        .encode(x=_x, y=_y, detail="curve:N")
    )
    _scatter = (
        alt.Chart(_points)
        .mark_circle(size=18, opacity=0.35, color="crimson")
        .encode(x=_x, y=_y, tooltip=["subject", "pct", "scaled_score"])
    )
    _rule = (
        alt.Chart(pl.DataFrame({"y": [100]}))
        .mark_rule(strokeDash=[4, 4])
        .encode(y="y:Q")
    )
    mo.vstack(
        [
            mo.md(
                "Black: $\\lfloor 80 + 40p \\rfloor$ (no score below 5%). Thin coloured lines: "
                "official KS2 tables. Red dots: scored Atom sittings (they lie on the "
                "black curve by construction; their spread shows where pupils are)."
            ),
            mo.ui.altair_chart(
                (_ks2_lines + _our_line + _scatter + _rule).properties(
                    width=720,
                    height=440,
                    title="Atom scaled-score curve vs KS2 2024-2026",
                )
            ),
        ]
    )
    return


@app.cell
def _(OUT, formula, pl, q):
    # How far the formula sits from each official table, over the raw scores
    # where both give a score.
    _t = q(
        f"select * from {OUT}.ks2_scaled_score_conversion where scaled_score is not null"
    ).with_columns(
        max_marks=pl.col("ks2_subject").replace_strict(
            {"reading": 50, "maths": 110, "gps": 70}, return_dtype=pl.Int64
        )
    )
    _t.with_columns(
        ours=pl.Series(
            formula(_t["raw_score"].to_numpy(), _t["max_marks"].to_numpy())
        ).fill_nan(None)
    ).drop_nulls("ours").group_by("test_year", "ks2_subject").agg(
        mean_abs_diff=(pl.col("ours") - pl.col("scaled_score")).abs().mean().round(2),
        max_abs_diff=(pl.col("ours") - pl.col("scaled_score")).abs().max(),
        rows_compared=pl.len(),
    ).sort("ks2_subject", "test_year")
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 10. Output summary

    Current score distribution per subject (one row per pupil and subject).
    """)
    return


@app.cell
def _(OUT, q):
    q(f"""
    select
        subject_name,
        count(*) as pupils,
        countif(not has_scaled_score) as no_score,
        round(avg(scaled_score), 1) as mean_scaled_score,
        min(scaled_score) as min_score,
        max(scaled_score) as max_score,
        round(100 * countif(meets_expected_standard) / count(*), 1) as pct_meeting_expected
    from {OUT}.gold__pupil_subject_scores
    where is_current
    group by subject_name
    order by pupils desc
    """)
    return


if __name__ == "__main__":
    app.run()
