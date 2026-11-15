{#
    One row per (sitting, question). Duplicate response rows for the same
    question in the same sitting are collapsed: the answer counts as correct
    only if every copy is correct. Copies share `answered_at`, so they always
    fall in the same daily batch.

    Incremental by day (microbatch on answered_at): each run reprocesses the
    last `answers_lookback_days` days and replaces them whole, so re-running is
    idempotent. No sitting or pupil rules are applied here (they can change
    after the fact); gold applies them on every run.
#}

{{ config(
    materialized='incremental',
    incremental_strategy='microbatch',
    event_time='answered_at',
    batch_size='day',
    begin=var('answers_begin'),
    lookback=var('answers_lookback_days'),
    concurrent_batches=true,
    partition_by={
        'field': 'answered_at',
        'data_type': 'timestamp',
        'granularity': 'day',
    },
    cluster_by=['session_id'],
) }}

with responses as (
    select * from {{ source('de_raw', 'responses') }}
),

course_hierarchy as (
    select * from {{ source('de_raw', 'course_hierarchy') }}
)

select
    {{ dbt_utils.generate_surrogate_key([
        'responses.session_id',
        'responses.question_id',
    ]) }}
        as answer_id,
    responses.session_id,
    responses.pupil_id,
    responses.question_id,
    course_hierarchy.subject_id,
    course_hierarchy.subject_name,
    logical_and(responses.is_correct) as is_correct,
    logical_and(responses.is_no_attempt) as is_no_attempt,
    count(*) as response_copies,
    count(distinct responses.is_correct) > 1 as has_conflicting_copies,
    min(responses.question_number) as question_number,
    min(responses.answered_at) as answered_at
from responses
inner join course_hierarchy
    on responses.question_id = course_hierarchy.question_id
group by
    responses.session_id,
    responses.pupil_id,
    responses.question_id,
    course_hierarchy.subject_id,
    course_hierarchy.subject_name
