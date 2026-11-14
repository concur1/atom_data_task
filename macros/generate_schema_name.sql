{#
    We can only write to one BigQuery dataset, so ignore any custom schema and
    always build into the target dataset. Medallion layers are expressed through
    folders and the `<layer>__<entity>` model-name prefix instead.
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {{ target.schema }}
{%- endmacro %}
