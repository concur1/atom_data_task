-- Within a (pupil, subject), each row's valid_to is the next row's
-- valid_from, so the history has no gaps or overlaps.
with ordered as (
    select
        pupil_subject_score_id,
        valid_to,
        lead(valid_from) over (
            partition by pupil_id, subject_id
            order by valid_from, session_id
        ) as next_valid_from
    from {{ ref('gold__pupil_subject_scores') }}
)

select *
from ordered
where valid_to is distinct from next_valid_from
