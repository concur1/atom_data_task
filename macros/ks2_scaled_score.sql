{#
    KS2-style scaled score (80-120) by linear rescaling of the proportion
    correct: floor(80 + 40 * correct / questions), i.e. 0% -> 80, 50% -> 100,
    100% -> 120. Integer arithmetic, so there is no floating-point rounding.
    Returns null ("N", no scaled score) below `ks2_min_pct` percent correct.
    See docs/adr/0002-scaled-score-curve.md.
#}
{% macro ks2_scaled_score(correct, questions) -%}
    case
        when {{ questions }} is null or {{ questions }} = 0 then null
        when {{ correct }} * 100 < {{ var('ks2_min_pct') }} * {{ questions }}
            then null
        else 80 + div(40 * {{ correct }}, {{ questions }})
    end
{%- endmacro %}
