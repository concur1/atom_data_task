{#
    One row per sitting, with the scoring rules applied as flags rather than
    filters so every exclusion can be counted. Sittings of deleted pupils are
    dropped entirely (treated as erasure).

    Rebuilt in full on every run (it's small, and its flags can change on any
    row), so deletes and completions always flow through to gold.
#}

with sittings as (
    select * from {{ source('de_raw', 'assessment_sittings') }}
),

pupils as (
    select * from {{ source('de_raw', 'pupils') }}
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
        case
            when coalesce(sittings.is_deleted, false) then 'deleted'
            when not coalesce(sittings.is_complete, false) then 'incomplete'
            when sittings.style = 'survey' then 'survey'
            when sittings.style = 'adaptive' then 'adaptive'
            when sittings.year_group_at_sitting > 6 then 'year_group_above_6'
        end as exclusion_reason
    from sittings
    inner join pupils on sittings.pupil_id = pupils.pupil_id
    where not coalesce(pupils.is_deleted, false)
)

select
    *,
    exclusion_reason is null as is_scorable
from flagged
