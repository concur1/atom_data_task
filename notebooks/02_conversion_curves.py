import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium", app_title="02 - KS2 conversion curves")


@app.cell
def _():
    import altair as alt
    import marimo as mo
    import numpy as np
    import polars as pl

    return alt, mo, np, pl


@app.cell
def _(mo):
    mo.md(r"""
    # 02 - KS2 raw → scaled score conversion curves

    Investigates the official KS2 conversion tables to decide how a pupil's
    % correct on an Atom assessment should map onto the 80-120 scale, and
    whether one algorithm can cover subjects that have no KS2 test.

    **Data:** `seeds/ks2_scaled_score_conversion.csv`, built from the GOV.UK
    tables in `reference_docs/` by `scripts/build_ks2_conversion_seed.py`
    (2024-2026; reading /50, maths /110, GPS /70). Runs offline - no BigQuery.
    """)
    return


@app.cell
def _(mo, pl):
    MAX_MARKS = {"reading": 50, "maths": 110, "gps": 70}
    KS2_SUBJECTS = list(MAX_MARKS)

    tables = (
        pl.read_csv(
            mo.notebook_dir().parent / "seeds" / "ks2_scaled_score_conversion.csv",
            schema={
                "test_year": pl.Int64,
                "ks2_subject": pl.String,
                "raw_score": pl.Int64,
                "scaled_score": pl.Int64,
            },
        )
        .with_columns(
            max_marks=pl.col("ks2_subject").replace_strict(
                MAX_MARKS, return_dtype=pl.Int64
            ),
        )
        .with_columns(
            pct_of_marks=(100 * pl.col("raw_score") / pl.col("max_marks")).round(1),
        )
    )
    YEARS = sorted(tables["test_year"].unique().to_list())
    tables
    return KS2_SUBJECTS, MAX_MARKS, YEARS, tables


@app.cell
def _(mo):
    mo.md(r"""
    ## 1. Key points of each table

    The three anchors GOV.UK defines: the minimum raw score that earns any
    scaled score (80+), the raw score that reaches the **expected standard
    (100)**, and the raw score where the scale tops out (120).
    """)
    return


@app.cell
def _(pl, tables):
    def _first_raw(condition: pl.Expr) -> pl.Expr:
        return pl.col("raw_score").filter(condition).min()

    anchors = (
        tables.group_by("test_year", "ks2_subject", "max_marks")
        .agg(
            raw_for_80=_first_raw(pl.col("scaled_score").is_not_null()),
            raw_for_100=_first_raw(pl.col("scaled_score") >= 100),
            raw_for_120=_first_raw(pl.col("scaled_score") == 120),
            raw_scores_per_point_max=pl.col("scaled_score")
            .drop_nulls()
            .value_counts()
            .struct.field("count")
            .max(),
        )
        .with_columns(
            (100 * pl.col(c) / pl.col("max_marks"))
            .round(1)
            .alias(f"pct_for_{c[-3:].lstrip('_')}")
            for c in ["raw_for_80", "raw_for_100", "raw_for_120"]
        )
        .sort("ks2_subject", "test_year")
    )
    anchors
    return (anchors,)


@app.cell
def _(mo):
    mo.md(r"""
    **Findings:**
    - Every table starts at raw 3 (raw 0-2 = no scaled score, "N").
    - The expected standard sits at **~49-56% of the marks** in every subject
      and year - the scale is centred on "half the marks".
    - The top of the scale is reached a few marks short of full marks.
    - `raw_scores_per_point_max`: in maths up to 5 raw marks share one scaled
      score - the curve is very flat in the middle.
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 2. The curves in % space

    Plotting scaled score against **% of available marks** puts the three
    subjects on one axis - the space our Atom % correct lives in.
    """)
    return


@app.cell
def _(YEARS, mo):
    year_picker = mo.ui.dropdown(
        options=[str(y) for y in YEARS], value=str(max(YEARS)), label="Test year"
    )
    year_picker
    return (year_picker,)


@app.cell
def _(alt, mo, pl, tables, year_picker):
    _year = int(year_picker.value)
    _chart = (
        alt.Chart(
            tables.filter(pl.col("test_year") == _year).drop_nulls("scaled_score")
        )
        .mark_line(interpolate="step-after")
        .encode(
            x=alt.X("pct_of_marks:Q", title="% of available marks"),
            y=alt.Y(
                "scaled_score:Q",
                title="Scaled score",
                scale=alt.Scale(domain=[78, 122]),
            ),
            color=alt.Color("ks2_subject:N", title="Subject"),
            tooltip=["ks2_subject", "raw_score", "pct_of_marks", "scaled_score"],
        )
        .properties(title=f"{_year} KS2 conversion curves", width=650, height=380)
    )
    _rule = (
        alt.Chart(pl.DataFrame({"y": [100]}))
        .mark_rule(strokeDash=[4, 4])
        .encode(y="y:Q")
    )
    mo.ui.altair_chart(_chart + _rule)
    return


@app.cell
def _(mo):
    mo.md(r"""
    **Findings:** the three subjects trace nearly the same S-shape in % space:
    steep near 0% and 100%, flat through the middle. Maths is the flattest in
    the middle, reading the steepest at the top.

    ## 3. How much does the test year matter?

    For each subject and raw score, the spread (max - min) of scaled scores
    across 2024-2026.
    """)
    return


@app.cell
def _(YEARS, pl, tables):
    by_year = tables.pivot(
        on="test_year",
        index=["ks2_subject", "raw_score", "pct_of_marks"],
        values="scaled_score",
    )
    _year_cols = [str(y) for y in YEARS]
    year_spread = by_year.with_columns(
        spread=pl.max_horizontal(_year_cols) - pl.min_horizontal(_year_cols)
    )
    year_spread.group_by("ks2_subject").agg(
        max_spread=pl.col("spread").max(),
        mean_spread=pl.col("spread").mean().round(2),
        raw_scores_with_spread_ge_3=(pl.col("spread") >= 3).sum(),
    ).sort("ks2_subject")
    return (year_spread,)


@app.cell
def _(alt, mo, year_spread):
    mo.ui.altair_chart(
        alt.Chart(year_spread.drop_nulls("spread"))
        .mark_line(interpolate="step-after")
        .encode(
            x=alt.X("pct_of_marks:Q", title="% of available marks"),
            y=alt.Y("spread:Q", title="Max - min scaled score across years"),
            color=alt.Color("ks2_subject:N", title="Subject"),
        )
        .properties(
            title="Year-to-year spread at the same raw score", width=650, height=250
        )
    )
    return


@app.cell
def _(mo):
    mo.md(r"""
    **Findings:** the year matters by ~1-2 points on average; the largest
    differences (up to 4) are at the low end of maths. Choosing one fixed year
    is a small, documented approximation.

    ## 4. A generic curve for subjects without a KS2 test

    Atom has subjects (Science, Verbal / Non-Verbal Reasoning, Screeners) with
    no KS2 test. Because the three real curves nearly coincide in % space,
    their average is a reasonable stand-in. Definition, for integer % `p`:

    1. per KS2 subject: `raw = floor(p × max_marks / 100)`, look up its scaled score
    2. generic score = mean of the subjects' scaled scores, rounded half-up
    3. **N** (no score) if fewer than 2 of the 3 subjects give a score
    """)
    return


@app.cell
def _(KS2_SUBJECTS, MAX_MARKS, pl, tables):
    def pct_lookup(year: int) -> pl.DataFrame:
        """Scaled score for each KS2 subject at each integer % of marks."""
        pcts = pl.DataFrame({"pct": list(range(101))})
        return pl.concat(
            pcts.with_columns(
                ks2_subject=pl.lit(subject),
                raw_score=pl.col("pct") * MAX_MARKS[subject] // 100,
            ).join(
                tables.filter(pl.col("test_year") == year).select(
                    "ks2_subject", "raw_score", "scaled_score"
                ),
                on=["ks2_subject", "raw_score"],
                how="left",
            )
            for subject in KS2_SUBJECTS
        )

    def generic_curve(year: int) -> pl.DataFrame:
        """The generic % -> scaled score curve for one test year."""
        return (
            pct_lookup(year)
            .group_by("pct")
            .agg(
                subjects_scored=pl.col("scaled_score").is_not_null().sum(),
                mean_scaled=pl.col("scaled_score").mean(),
            )
            .with_columns(
                generic_scaled_score=pl.when(pl.col("subjects_scored") >= 2)
                .then((pl.col("mean_scaled") + 0.5).floor())
                .cast(pl.Int64)
            )
            .sort("pct")
            .select("pct", "subjects_scored", "generic_scaled_score")
        )

    return generic_curve, pct_lookup


@app.cell
def _(generic_curve, year_picker):
    generic = generic_curve(int(year_picker.value))
    generic
    return (generic,)


@app.cell
def _(alt, generic, mo, pct_lookup, pl, year_picker):
    _real = pct_lookup(int(year_picker.value)).select(
        "pct", pl.col("ks2_subject").alias("curve"), "scaled_score"
    )
    _gen = generic.select(
        "pct",
        pl.lit("GENERIC").alias("curve"),
        pl.col("generic_scaled_score").alias("scaled_score"),
    )
    mo.ui.altair_chart(
        alt.Chart(pl.concat([_real, _gen]).drop_nulls("scaled_score"))
        .mark_line(interpolate="step-after")
        .encode(
            x=alt.X("pct:Q", title="% correct"),
            y=alt.Y(
                "scaled_score:Q",
                title="Scaled score",
                scale=alt.Scale(domain=[78, 122]),
            ),
            color=alt.Color("curve:N", title="Curve"),
            strokeWidth=alt.condition(
                alt.datum.curve == "GENERIC", alt.value(3.5), alt.value(1.2)
            ),
        )
        .properties(
            title=f"Generic curve vs real curves ({year_picker.value})",
            width=650,
            height=380,
        )
    )
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 5. How faithful is the generic curve - and is a simple formula good enough?

    Compared against each real table (integer % 0-100 where both give a score):

    - **generic curve** (section 4)
    - **3-point formula**: straight lines through the averaged anchors
      (min score → 80, expected standard → 100, top → 120) - the simplest
      thing you could write down as a formula.
    """)
    return


@app.cell
def _(KS2_SUBJECTS, YEARS, anchors, generic_curve, pct_lookup, pl):
    def three_point(year: int) -> pl.DataFrame:
        """Piecewise-linear curve through the averaged 80 / 100 / 120 anchors."""
        a = (
            anchors.filter(pl.col("test_year") == year)
            .select(
                pl.col("pct_for_80").mean(),
                pl.col("pct_for_100").mean(),
                pl.col("pct_for_120").mean(),
            )
            .row(0)
        )
        lo, mid, hi = a
        p = pl.col("pct").cast(pl.Float64)
        return pl.DataFrame({"pct": list(range(101))}).with_columns(
            three_point_scaled_score=pl.when(p < lo)
            .then(None)
            .when(p >= hi)
            .then(120.0)
            .when(p < mid)
            .then(80 + 20 * (p - lo) / (mid - lo))
            .otherwise(100 + 20 * (p - mid) / (hi - mid))
            .add(0.5)
            .floor()
            .cast(pl.Int64)
        )

    _errors = []
    for _year in YEARS:
        _cmp = (
            pct_lookup(_year)
            .join(generic_curve(_year), on="pct")
            .join(three_point(_year), on="pct")
            .drop_nulls(
                ["scaled_score", "generic_scaled_score", "three_point_scaled_score"]
            )
        )
        _errors.append(
            _cmp.group_by("ks2_subject")
            .agg(
                generic_mean_abs_error=(
                    pl.col("generic_scaled_score") - pl.col("scaled_score")
                )
                .abs()
                .mean()
                .round(2),
                generic_max_abs_error=(
                    pl.col("generic_scaled_score") - pl.col("scaled_score")
                )
                .abs()
                .max(),
                three_point_mean_abs_error=(
                    pl.col("three_point_scaled_score") - pl.col("scaled_score")
                )
                .abs()
                .mean()
                .round(2),
                three_point_max_abs_error=(
                    pl.col("three_point_scaled_score") - pl.col("scaled_score")
                )
                .abs()
                .max(),
            )
            .with_columns(test_year=pl.lit(_year))
        )
    pl.concat(_errors).select(
        "test_year", "ks2_subject", pl.exclude("test_year", "ks2_subject")
    ).sort(
        "test_year", pl.col("ks2_subject").replace_strict(KS2_SUBJECTS, list(range(3)))
    )
    return


@app.cell
def _(mo):
    mo.md(r"""
    **Findings:** the generic curve reproduces each real table to within
    ~1 point on average (max 4, low-end maths); the 3-point formula is roughly
    2-3× worse.

    ## 6. What the government literature says about the curves

    The conversion tables are published every year, but the **method** is only
    documented in STA's *National curriculum test handbook*
    ([2019 edition](https://dera.ioe.ac.uk//35121/1/2019_national_curriculum_test_handbook.pdf),
    §13 "Standard setting and standards maintenance"; the
    [test development handbook](https://www.gov.uk/government/publications/national-curriculum-test-development-handbook/test-development-handbook-2023)
    is the current successor):

    1. **Standard setting (2016, once).** Two independent panels of teachers per
       test ran a *Bookmark* exercise: items ordered by difficulty under "a
       two-parameter IRT model, using a response probability of two-thirds";
       teachers marked where a "minimally capable pupil just at the expected
       standard" would have a two-thirds chance of success. 2016 KS2 cut scores:
       reading 21/50, maths 60/110, GPS 43/70.
    2. **Standards maintenance (2017 onwards).** "Standalone anchor tests were
       administered to a representative sample of pupils who took the live test
       ... a multiple-group, two-parameter graded response IRT model was run,
       enabling us to equate from the 2016 live test" to the current one. This
       is why the raw mark for 100 moves year to year.
    3. **Scaling - the curve itself.** "A linear IRT scale transformation was
       used" (Equation 1):

    $$SC_i = 100 + \frac{\sigma(SC)}{\sigma(\theta)}\left(\theta_{X_i} - \theta_{cut}\right)$$

    where $\theta_{X_i}$ is the IRT ability for raw score $X_i$ (summed-score
    likelihood estimate in flexMIRT) and $\theta_{cut}$ the ability at the
    expected standard. "Scaled scores were rounded down to the integer below",
    and the scale is capped at 80-120 with a minimum raw score for 80.

    **So the scaled score is linear in ability, not in marks.** The S-shape in
    §2 is the test characteristic curve (raw marks vs ability) seen sideways.
    The item parameters and $\sigma(SC)/\sigma(\theta)$ aren't published, so the
    exact tables can't be recomputed - but the structure suggests a formula.

    ## 7. A formula from Equation 1

    For a test of similar items, ability is roughly the **log-odds of the
    proportion correct**: $\theta \approx \text{logit}(p) = \ln\frac{p}{1-p}$.
    Substituting into Equation 1 gives a two-parameter formula:

    $$SC = \text{clamp}_{80}^{120}\left(\left\lfloor 100 + k\,\big(\text{logit}(p) - \text{logit}(p_{cut})\big)\right\rfloor\right)$$

    - $p_{cut}$: proportion correct at the expected standard
    - $k$: scaled-score points per logit (the slope)

    Fit by grid search, first per table, then one $(k, p_{cut})$ for all nine.
    """)
    return


@app.cell
def _(np, pl, tables):
    K_GRID = np.round(np.arange(4.0, 14.0, 0.1), 1)
    P_CUT_GRID = np.round(np.arange(0.40, 0.60, 0.002), 3)

    def logit_formula(p: np.ndarray, k: float, p_cut: float) -> np.ndarray:
        """Equation-1-style scaled score from proportion correct (vectorised)."""
        p = np.clip(p, 1e-6, 1 - 1e-6)
        raw = np.floor(100 + k * (np.log(p / (1 - p)) - np.log(p_cut / (1 - p_cut))))
        return np.clip(raw, 80, 120)

    def fit_logit(df: pl.DataFrame) -> tuple[float, float, float, int]:
        """Grid-search (k, p_cut) minimising mean absolute error on scored rows."""
        p = (df["raw_score"] / df["max_marks"]).to_numpy()
        actual = df["scaled_score"].to_numpy()
        best = (np.inf, 0.0, 0.0, 0)
        for k in K_GRID:
            for p_cut in P_CUT_GRID:
                err = np.abs(logit_formula(p, k, p_cut) - actual)
                if err.mean() < best[0]:
                    best = (float(err.mean()), float(k), float(p_cut), int(err.max()))
        return best

    scored = tables.drop_nulls("scaled_score")
    _rows = []
    for (_year, _subject), _df in scored.group_by("test_year", "ks2_subject"):
        _mae, _k, _p_cut, _max = fit_logit(_df)
        _rows.append((_year, _subject, _k, _p_cut, round(_mae, 2), _max))
    per_table_fit = pl.DataFrame(
        _rows,
        schema=[
            "test_year",
            "ks2_subject",
            "k",
            "p_cut",
            "mean_abs_error",
            "max_abs_error",
        ],
        orient="row",
    ).sort("ks2_subject", "test_year")
    per_table_fit
    return fit_logit, logit_formula, scored


@app.cell
def _(fit_logit, logit_formula, pl, scored):
    UNIVERSAL_MAE, UNIVERSAL_K, UNIVERSAL_P_CUT, _ = fit_logit(scored)
    _pred = logit_formula(
        (scored["raw_score"] / scored["max_marks"]).to_numpy(),
        UNIVERSAL_K,
        UNIVERSAL_P_CUT,
    )
    universal_errors = (
        scored.with_columns(formula=pl.Series(_pred).cast(pl.Int64))
        .with_columns(abs_error=(pl.col("formula") - pl.col("scaled_score")).abs())
        .group_by("test_year", "ks2_subject")
        .agg(
            mean_abs_error=pl.col("abs_error").mean().round(2),
            max_abs_error=pl.col("abs_error").max(),
        )
        .sort("ks2_subject", "test_year")
    )
    print(
        f"universal formula: k = {UNIVERSAL_K}, p_cut = {UNIVERSAL_P_CUT}, "
        f"mean abs error over all 9 tables = {UNIVERSAL_MAE:.2f}"
    )
    universal_errors
    return UNIVERSAL_K, UNIVERSAL_P_CUT


@app.cell
def _(
    UNIVERSAL_K,
    UNIVERSAL_P_CUT,
    alt,
    generic,
    logit_formula,
    mo,
    np,
    pct_lookup,
    pl,
    year_picker,
):
    _pcts = np.arange(101)
    _formula = pl.DataFrame(
        {
            "pct": _pcts,
            "curve": "LOGIT FORMULA",
            "scaled_score": logit_formula(
                _pcts / 100, UNIVERSAL_K, UNIVERSAL_P_CUT
            ).astype(int),
        }
    ).filter(pl.col("pct") >= 5)  # below ~4% every table gives no score
    _real = pct_lookup(int(year_picker.value)).select(
        "pct", pl.col("ks2_subject").alias("curve"), "scaled_score"
    )
    _gen = generic.select(
        "pct",
        pl.lit("GENERIC").alias("curve"),
        pl.col("generic_scaled_score").alias("scaled_score"),
    )
    mo.ui.altair_chart(
        alt.Chart(
            pl.concat([_real, _gen, _formula], how="vertical_relaxed").drop_nulls(
                "scaled_score"
            )
        )
        .mark_line(interpolate="step-after")
        .encode(
            x=alt.X("pct:Q", title="% correct"),
            y=alt.Y(
                "scaled_score:Q",
                title="Scaled score",
                scale=alt.Scale(domain=[78, 122]),
            ),
            color=alt.Color("curve:N", title="Curve"),
            strokeDash=alt.condition(
                alt.datum.curve == "LOGIT FORMULA", alt.value([6, 3]), alt.value([1, 0])
            ),
        )
        .properties(
            title=f"Logit formula vs generic curve vs real curves ({year_picker.value})",
            width=650,
            height=380,
        )
    )
    return


@app.cell
def _(mo):
    mo.md(r"""
    **Findings:**
    - Fitted **per table**, the two-parameter logit formula reproduces the
      official tables almost exactly (mean error ~0.2-0.4 points, max 1-3):
      Equation 1 with $\theta \approx \text{logit}(p)$ really is how these
      curves behave.
    - **One formula for every table** ($k \approx 7.3$, $p_{cut} \approx 0.5$)
      is as faithful as the generic curve (~1 point mean error) but is a
      single line of SQL with two documented constants:
      `least(120, greatest(80, floor(100 + 7.3 * ln(p / (1 - p)))))`.
    - Fitted $p_{cut}$ sits at 0.48-0.54 in every table: the expected standard
      is consistently "about half the marks".

    ## 8. Options for scoring Atom subjects (decision pending)

    | Option | Maths / English | Other subjects | Reproducible as | Faithfulness |
    |---|---|---|---|---|
    | A. Real tables + generic curve | KS2 table | averaged curve | a dbt model over the seed | exact / ~1 pt |
    | B. Real tables + logit formula | KS2 table | universal formula | seed + 1 SQL expression | exact / ~1 pt |
    | C. Logit formula everywhere | universal formula | universal formula | 1 SQL expression | ~1 pt |

    Common to all: map **% correct → proportion of marks** directly (assumes
    Atom assessments ≈ KS2 difficulty, 1 question ≈ 1 mark); below the minimum
    (~4% / 3 marks) → **no scaled score (N)**, never rounded up to 80; record
    the method and table year used in the output.
    """)
    return


if __name__ == "__main__":
    app.run()
