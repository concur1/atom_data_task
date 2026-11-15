import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium", app_title="03 - Reconciliation")


@app.cell
def _():
    import os

    import altair as alt
    import marimo as mo
    import numpy as np
    import polars as pl
    from google.cloud import bigquery
    from google.oauth2.credentials import Credentials

    return Credentials, alt, bigquery, mo, np, os, pl


@app.cell
def _(mo):
    mo.md(r"""
    # 03 - Reconciling our scores with the KS2 conversion tables

    Compares the scores in `gold__pupil_subject_scores` (linear rescaling,
    $\lfloor 80 + 40p \rfloor$, ADR 0002) with the official 2024-2026 KS2
    conversion tables (seed `ks2_scaled_score_conversion`).

    Run `make build` first. **Auth:** gcloud application-default credentials,
    or a raw OAuth token in `CLOUDSDK_AUTH_ACCESS_TOKEN`.
    """)
    return


@app.cell
def _(Credentials, bigquery, np, os, pl):
    _project = os.environ.get("DBT_GCP_PROJECT", "atom-analytics-candidates")
    _dataset = os.environ.get("DBT_DATASET", "owen_cain")
    _token = os.environ.get("CLOUDSDK_AUTH_ACCESS_TOKEN")
    _client = bigquery.Client(
        project=_project,
        location="europe-west2",
        credentials=Credentials(_token) if _token else None,
    )

    def _load(table: str) -> pl.DataFrame:
        sql = f"select * from `{_project}.{_dataset}.{table}`"
        result = pl.from_arrow(_client.query(sql).to_arrow())
        assert isinstance(result, pl.DataFrame)
        return result

    MAX_MARKS = {"reading": 50, "maths": 110, "gps": 70}
    gold = _load("gold__pupil_subject_scores")
    tables = (
        _load("ks2_scaled_score_conversion")
        .drop_nulls("scaled_score")
        .with_columns(
            max_marks=pl.col("ks2_subject").replace_strict(
                MAX_MARKS, return_dtype=pl.Int64
            )
        )
    )

    def our_score(correct: np.ndarray, total: np.ndarray) -> np.ndarray:
        """ADR 0002: floor(80 + 40 * correct / total); NaN below 5% (N)."""
        correct = np.asarray(correct, dtype=np.int64)
        total = np.asarray(total, dtype=np.int64)
        score = (80 + (40 * correct) // total).astype(float)
        return np.where(correct * 100 < 5 * total, np.nan, score)

    return MAX_MARKS, gold, our_score, tables


@app.cell
def _(mo):
    mo.md(r"""
    ## 1. Our formula against every official table

    For each raw score in each table, our score for the same proportion of
    marks vs the official scaled score.
    """)
    return


@app.cell
def _(our_score, pl, tables):
    compared = tables.with_columns(
        pct_of_marks=100 * pl.col("raw_score") / pl.col("max_marks"),
        ours=pl.Series(
            our_score(tables["raw_score"].to_numpy(), tables["max_marks"].to_numpy())
        ).fill_nan(None),
    ).drop_nulls("ours")

    compared.group_by("ks2_subject", "test_year").agg(
        raw_scores=pl.len(),
        mean_abs_diff=(pl.col("ours") - pl.col("scaled_score")).abs().mean().round(2),
        max_abs_diff=(pl.col("ours") - pl.col("scaled_score")).abs().max(),
        agree_on_expected_standard_pct=(
            100 * ((pl.col("ours") >= 100) == (pl.col("scaled_score") >= 100)).mean()
        ).round(1),
    ).sort("ks2_subject", "test_year")
    return (compared,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 2. Our curve vs the KS2 curves

    Thin lines: the official tables, plotted against % of available marks.
    Black: our formula. Red dots: every scored Atom sitting in gold.
    """)
    return


@app.cell
def _(alt, compared, gold, mo, np, our_score, pl):
    _steps = np.arange(401)  # 0.25% steps
    _ours = pl.DataFrame(
        {"pct": _steps / 4, "scaled_score": our_score(_steps, np.full(401, 400))}
    ).filter(pl.col("scaled_score").is_not_nan())
    _ks2 = compared.select(
        pct="pct_of_marks",
        scaled_score="scaled_score",
        curve=pl.format("KS2 {} {}", pl.col("ks2_subject"), pl.col("test_year")),
    )
    _atom = gold.drop_nulls("scaled_score").select(
        pct=100 * pl.col("proportion_correct"),
        scaled_score="scaled_score",
        subject="subject_name",
    )
    _x = alt.X(
        "pct:Q", title="% correct / % of marks", scale=alt.Scale(domain=[0, 100])
    )
    _y = alt.Y(
        "scaled_score:Q", title="Scaled score", scale=alt.Scale(domain=[78, 122])
    )
    mo.ui.altair_chart(
        (
            alt.Chart(_ks2)
            .mark_line(interpolate="step-after", opacity=0.5, strokeWidth=1.2)
            .encode(x=_x, y=_y, color=alt.Color("curve:N", title="Official table"))
            + alt.Chart(_ours)
            .mark_line(interpolate="step-after", color="black", strokeWidth=2.5)
            .encode(x=_x, y=_y)
            + alt.Chart(_atom)
            .mark_circle(size=18, opacity=0.35, color="crimson")
            .encode(x=_x, y=_y, tooltip=["subject", "pct", "scaled_score"])
        ).properties(width=720, height=440, title="Our formula vs KS2 2024-2026")
    )
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 3. Our scores vs reading Atom sittings off the 2026 tables

    For Maths and English sittings in gold: the score our formula gave vs the
    score the 2026 KS2 maths / reading table would give the same proportion
    of marks.
    """)
    return


@app.cell
def _(MAX_MARKS, gold, pl, tables):
    _table_for = {"Maths": "maths", "English": "reading"}
    _t2026 = tables.filter(pl.col("test_year") == 2026).select(
        "ks2_subject", "raw_score", table_2026_score="scaled_score"
    )
    (
        gold.filter(pl.col("subject_name").is_in(list(_table_for)))
        .with_columns(ks2_subject=pl.col("subject_name").replace_strict(_table_for))
        .with_columns(
            raw_score=pl.col("correct")
            * pl.col("ks2_subject").replace_strict(MAX_MARKS, return_dtype=pl.Int64)
            // pl.col("questions")
        )
        .join(_t2026, on=["ks2_subject", "raw_score"], how="inner")
        .drop_nulls("scaled_score")
        .group_by("subject_name")
        .agg(
            sittings=pl.len(),
            mean_diff=(pl.col("scaled_score") - pl.col("table_2026_score"))
            .mean()
            .round(2),
            mean_abs_diff=(pl.col("scaled_score") - pl.col("table_2026_score"))
            .abs()
            .mean()
            .round(2),
            max_abs_diff=(pl.col("scaled_score") - pl.col("table_2026_score"))
            .abs()
            .max(),
            agree_on_expected_standard_pct=(
                100
                * (
                    (pl.col("scaled_score") >= 100)
                    == (pl.col("table_2026_score") >= 100)
                ).mean()
            ).round(1),
        )
    )
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 4. Gold applies the formula exactly

    Every gold score recomputed in Python from `correct` and `questions`.
    """)
    return


@app.cell
def _(gold, our_score, pl):
    _recomputed = pl.Series(
        our_score(gold["correct"].to_numpy(), gold["questions"].to_numpy())
    ).fill_nan(None)
    gold.with_columns(recomputed=_recomputed.cast(pl.Int64)).select(
        rows=pl.len(),
        mismatches=(
            pl.col("recomputed").ne_missing(pl.col("scaled_score"))
            | (pl.col("recomputed").is_null() == pl.col("has_scaled_score"))
        ).sum(),
    )
    return


if __name__ == "__main__":
    app.run()
