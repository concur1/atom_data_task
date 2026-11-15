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

    The official tables are plotted against % of available marks (one colour
    per subject, darker = later year). Black: our formula. Red dots: every
    scored Atom sitting in gold (they sit on the black line by construction).
    """)
    return


@app.cell
def _(alt, compared, gold, mo, np, our_score, pl):
    OURS = "Our formula: floor(80 + 40p)"
    ATOM = "Atom sittings (gold)"

    _steps = np.arange(401)  # 0.25% steps
    _ours = pl.DataFrame(
        {
            "pct": _steps / 4,
            "scaled_score": our_score(_steps, np.full(401, 400)),
            "curve": OURS,
        }
    ).filter(pl.col("scaled_score").is_not_nan())
    _ks2 = compared.select(
        pct="pct_of_marks",
        scaled_score=pl.col("scaled_score").cast(pl.Float64),
        curve=pl.format("KS2 {} {}", pl.col("ks2_subject"), pl.col("test_year")),
    )
    _atom = gold.drop_nulls("scaled_score").select(
        pct=100 * pl.col("proportion_correct"),
        scaled_score="scaled_score",
        subject="subject_name",
        curve=pl.lit(ATOM),
    )

    # One colour key for everything: ours in black, Atom sittings in red, and
    # the official tables in a shade per subject (gps blue, maths orange,
    # reading green; darker = later year).
    _ks2_curves = sorted(_ks2["curve"].unique().to_list())
    _years = sorted(compared["test_year"].unique().to_list())
    _ks2_shades = {
        "gps": ["#9ecae9", "#4c78a8", "#1f4e79"],
        "maths": ["#ffbf79", "#f58518", "#b85c00"],
        "reading": ["#88d27a", "#54a24b", "#2e6b28"],
    }
    _colour = alt.Color(
        "curve:N",
        title=None,
        scale=alt.Scale(
            domain=[OURS, ATOM, *_ks2_curves],
            range=[
                "black",
                "crimson",
                *(
                    _ks2_shades[c.split()[1]][min(_years.index(int(c.split()[2])), 2)]
                    for c in _ks2_curves
                ),
            ],
        ),
        legend=alt.Legend(orient="right", symbolStrokeWidth=3),
    )
    _x = alt.X(
        "pct:Q", title="% correct / % of marks", scale=alt.Scale(domain=[0, 100])
    )
    _y = alt.Y(
        "scaled_score:Q", title="Scaled score", scale=alt.Scale(domain=[78, 122])
    )
    _lines = (
        alt.Chart(pl.concat([_ks2, _ours]))
        .mark_line(interpolate="step-after")
        .encode(
            x=_x,
            y=_y,
            color=_colour,
            strokeWidth=alt.condition(
                alt.datum.curve == OURS, alt.value(3), alt.value(1.2)
            ),
            opacity=alt.condition(
                alt.datum.curve == OURS, alt.value(1), alt.value(0.6)
            ),
        )
    )
    _dots = (
        alt.Chart(_atom)
        .mark_circle(size=18, opacity=0.35)
        .encode(x=_x, y=_y, color=_colour, tooltip=["subject", "pct", "scaled_score"])
    )
    mo.ui.altair_chart(
        (_lines + _dots).properties(
            width=720, height=440, title="Our formula vs KS2 2024-2026"
        )
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


@app.cell
def _(mo):
    mo.md(r"""
    ## 5. Distribution of the final scores

    How the scores in gold are spread across the 80-120 scale (every scored
    sitting, and each pupil's current score). Because the scale is linear in
    % correct, the spread of scores is simply 40 × the spread of % correct.
    """)
    return


@app.cell
def _(alt, gold, mo, pl):
    _scored = gold.filter(pl.col("has_scaled_score"))
    _by_subject = (
        _scored.group_by("subject_name")
        .agg(
            sittings=pl.len(),
            mean=pl.col("scaled_score").mean().round(1),
            sd=pl.col("scaled_score").std().round(1),
            p5=pl.col("scaled_score").quantile(0.05, "nearest"),
            p25=pl.col("scaled_score").quantile(0.25, "nearest"),
            median=pl.col("scaled_score").median(),
            p75=pl.col("scaled_score").quantile(0.75, "nearest"),
            p95=pl.col("scaled_score").quantile(0.95, "nearest"),
            pct_95_to_109=(
                100 * pl.col("scaled_score").is_between(95, 109).mean()
            ).round(1),
            pct_meeting_expected=(100 * pl.col("meets_expected_standard").mean()).round(
                1
            ),
            pct_at_80_or_120=(
                100 * pl.col("scaled_score").is_in([80, 120]).mean()
            ).round(1),
        )
        .sort("sittings", descending=True)
    )
    _hist = (
        alt.Chart(
            pl.concat(
                [
                    _scored.select("scaled_score", view=pl.lit("every scored sitting")),
                    _scored.filter(pl.col("is_current")).select(
                        "scaled_score",
                        view=pl.lit("current score per pupil and subject"),
                    ),
                ]
            )
        )
        .mark_bar()
        .encode(
            x=alt.X(
                "scaled_score:Q",
                bin=alt.Bin(extent=[80, 122], step=2),
                title="Scaled score",
            ),
            y=alt.Y("count():Q", title="Count"),
            row=alt.Row("view:N", title=None),
        )
        .properties(width=680, height=160)
        .resolve_scale(y="independent")
    )
    mo.vstack([_by_subject, mo.ui.altair_chart(_hist)])
    return


@app.cell
def _(mo):
    mo.md(r"""
    **Findings:** scores bunch in the middle of the scale. Across all scored
    sittings the middle half sits between about 96 and 108, around two thirds
    of scores fall in 95-109, and very few reach 80 or 120. The scale's tails
    are barely used, which makes it hard to tell apart pupils in the middle.
    (The comb-like spikes come from common sitting lengths: with 25
    questions, for example, scores move in steps of 1.6 points, so some
    integer scores occur more often than their neighbours.)
    Finding a curve that spreads scores out more is listed under "What I would
    do next" in the README.
    """)
    return


if __name__ == "__main__":
    app.run()
