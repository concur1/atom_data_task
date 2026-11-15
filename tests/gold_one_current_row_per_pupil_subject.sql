-- Every (pupil, subject) in gold has exactly one current row.
select
    pupil_id,
    subject_id,
    countif(is_current) as current_rows
from {{ ref('gold__pupil_subject_scores') }}
group by pupil_id, subject_id
having countif(is_current) != 1
