{#
    One row per (sitting, question). Duplicate response rows for the same
    question in the same sitting are collapsed: the answer counts as correct
    only if every copy is correct. Responses without a known sitting (or whose
    pupil was deleted) are dropped by the join to silver__sittings.
#}

with responses as (
    select * from {{ source('de_raw', 'responses') }}
),

sittings as (
    select * from {{ ref('silver__sittings') }}
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
    sittings.pupil_id,
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
inner join sittings on responses.session_id = sittings.session_id
inner join
    course_hierarchy
    on responses.question_id = course_hierarchy.question_id
group by
    responses.session_id,
    sittings.pupil_id,
    responses.question_id,
    course_hierarchy.subject_id,
    course_hierarchy.subject_name
