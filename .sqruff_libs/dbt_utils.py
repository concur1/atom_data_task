"""Lint-time stand-in for dbt_utils macros (sqruff's jinja templater only).

Renders a placeholder with the same SQL shape so the surrounding SQL lints;
dbt uses the real package at build time.
"""


def generate_surrogate_key(field_list: list[str]) -> str:
    return "md5(concat(" + ", ".join(f"cast({f} as string)" for f in field_list) + "))"
