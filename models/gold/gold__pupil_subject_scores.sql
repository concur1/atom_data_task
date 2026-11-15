{#
    Type-2 history of each pupil's KS2-style scaled score per subject: one row
    per scored sitting, valid from that sitting's finish until the next one.

    Score as of T: valid_from <= T and (valid_to > T or valid_to is null).
    Current score:  is_current.

    Rebuilt in full on every run from the incremental silver models, applying
    the sitting rules (is_scorable) and dropping deleted pupils, so deletes and
    rule changes always take effect and valid_to is always consistent.
#}

with sitting_scores as (
    select * from {{ ref('silver__sitting_scores') }}
),

sittings as (
    select * from {{ ref('silver__sittings') }}
    where is_scorable
),

scored_sittings as (
    select
        sitting_scores.*,
        sittings.assessment_id,
        sittings.year_group_at_sitting,
        sittings.finished_at
    from sitting_scores
    inner join sittings on sitting_scores.session_id = sittings.session_id
),

versioned as (
    select
        *,
        lead(finished_at) over (
            partition by pupil_id, subject_id
            order by finished_at, session_id
        ) as next_finished_at,
        row_number() over (
            partition by pupil_id, subject_id
            order by finished_at desc, session_id desc
        ) = 1 as is_latest
    from scored_sittings
)

select
    {{ dbt_utils.generate_surrogate_key([
        'pupil_id',
        'subject_id',
        'session_id',
    ]) }}
        as pupil_subject_score_id,
    pupil_id,
    subject_id,
    subject_name,
    session_id,
    assessment_id,
    year_group_at_sitting,
    questions,
    correct,
    p as proportion_correct,
    scaled_score,
    has_scaled_score,
    meets_expected_standard,
    finished_at as valid_from,
    next_finished_at as valid_to,
    is_latest as is_current,
    '{{ var("scoring_method") }}' as scoring_method
from versioned
