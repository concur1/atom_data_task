{#
    One row per (sitting, subject): questions answered, correct answers and
    the scaled score. No sitting or pupil rules are applied here; gold applies
    them on every run.

    Incremental: each run re-scores every sitting that has an answer from the
    last `answers_lookback_days` days (using all of that sitting's answers,
    not just the new ones) and merges on (session_id, subject_id).
#}

{{ config(
    materialized='incremental',
    incremental_strategy='merge',
    unique_key=['session_id', 'subject_id'],
    cluster_by=['session_id'],
) }}

with answers as (
    select * from {{ ref('silver__answers') }}
    {% if is_incremental() %}
        where session_id in (
            select recent.session_id
            from {{ ref('silver__answers') }} as recent
            where recent.answered_at >= (
                select
                    timestamp_sub(
                        max(existing.last_answered_at),
                        interval {{ var('answers_lookback_days') }} day
                    )
                from {{ this }} as existing
            )
        )
    {% endif %}
),

totals as (
    select
        session_id,
        pupil_id,
        subject_id,
        subject_name,
        count(*) as questions,
        countif(is_correct) as correct,
        max(answered_at) as last_answered_at
    from answers
    group by session_id, pupil_id, subject_id, subject_name
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
