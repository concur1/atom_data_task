{#
    One row per sitting, with the scoring rules applied as flags rather than
    filters so every exclusion can be counted. Sittings of deleted pupils are
    dropped entirely (treated as erasure).
#}

with sittings as (
    select * from {{ source('de_raw', 'assessment_sittings') }}
),

pupils as (
    select * from {{ source('de_raw', 'pupils') }}
),

response_counts as (
    select
        session_id,
        count(*) as response_rows
    from {{ source('de_raw', 'responses') }}
    group by session_id
),

flagged as (
    select
        sittings.session_id,
        sittings.pupil_id,
        sittings.assessment_id,
        sittings.session_type,
        sittings.style,
        sittings.year_group_at_sitting,
        sittings.total_questions,
        sittings.is_complete,
        sittings.is_deleted,
        sittings.started_at,
        sittings.finished_at,
        coalesce(response_counts.response_rows, 0) as response_rows,
        case
            when coalesce(sittings.is_deleted, false) then 'deleted'
            when not coalesce(sittings.is_complete, false) then 'incomplete'
            when sittings.style = 'survey' then 'survey'
            when sittings.style = 'adaptive' then 'adaptive'
            when sittings.year_group_at_sitting > 6 then 'year_group_above_6'
            when response_counts.session_id is null then 'no_responses'
        end as exclusion_reason
    from sittings
    inner join pupils on sittings.pupil_id = pupils.pupil_id
    left join
        response_counts
        on sittings.session_id = response_counts.session_id
    where not coalesce(pupils.is_deleted, false)
)

select
    *,
    exclusion_reason is null as is_scorable
from flagged
