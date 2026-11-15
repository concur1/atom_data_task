{#
    One row per scorable sitting and subject: proportion correct and the
    KS2-shaped scaled score (null with status 'N' below the minimum).
#}

with sittings as (
    select * from {{ ref('silver__sittings') }}
    where is_scorable
),

answers as (
    select * from {{ ref('silver__answers') }}
),

totals as (
    select
        sittings.session_id,
        sittings.pupil_id,
        sittings.assessment_id,
        sittings.year_group_at_sitting,
        sittings.finished_at,
        answers.subject_id,
        answers.subject_name,
        count(*) as questions,
        countif(answers.is_correct) as correct
    from sittings
    inner join answers on sittings.session_id = answers.session_id
    group by
        sittings.session_id,
        sittings.pupil_id,
        sittings.assessment_id,
        sittings.year_group_at_sitting,
        sittings.finished_at,
        answers.subject_id,
        answers.subject_name
),

scored as (
    select
        *,
        correct / questions as p,
        {{ ks2_scaled_score('correct', 'questions') }} as scaled_score
    from totals
)

select
    *,
    scaled_score is not null as has_scaled_score,
    coalesce(scaled_score >= 100, false) as meets_expected_standard
from scored
