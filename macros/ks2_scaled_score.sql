{#
    KS2-shaped scaled score (80-120) for a proportion correct `p`.

    STA's scaled score is linear in IRT ability; logit(p) approximates ability,
    so: floor(100 + slope * (logit(p) - logit(p_cut))), clamped to 80-120.
    Returns null ("N", no scaled score) when p is below `ks2_min_p`.
    See docs/adr/0001-scoring-data-model.md.
#}
{% macro ks2_scaled_score(p) -%}
    {%- set slope = var('ks2_logit_slope') -%}
    {%- set p_cut = var('ks2_logit_p_cut') -%}
    case
        when {{ p }} is null or {{ p }} < {{ var('ks2_min_p') }} then null
        when {{ p }} >= 1 then 120
        else least(
            120,
            greatest(
                80,
                cast(floor(
                    100 + {{ slope }} * (
                        ln({{ p }} / (1 - {{ p }}))
                        - ln({{ p_cut }} / (1 - {{ p_cut }}))
                    )
                ) as int64)
            )
        )
    end
{%- endmacro %}
