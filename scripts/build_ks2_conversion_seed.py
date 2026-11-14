"""Build seeds/ks2_scaled_score_conversion.csv from the GOV.UK tables in reference_docs/.

The reference docs are copies of the GOV.UK "key stage 2 scaled score conversion
tables" pages, one file per test year. Each has a heading line per subject, a
"Raw score Scaled score" header, then one "<raw> <scaled>" row per raw score,
where the lowest raw scores read "No scaled score" (sometimes as a range,
e.g. "0 - 2").

Run: uv run python scripts/build_ks2_conversion_seed.py
"""

import csv
import re
from pathlib import Path
from typing import NamedTuple

ROOT = Path(__file__).resolve().parent.parent
SEED = ROOT / "seeds" / "ks2_scaled_score_conversion.csv"
SOURCES = {
    2024: "2024-key-stage-2-scaled-scored-conversion-tables.md",
    2025: "2025-key-stage-2-scored-conversion-table.md",
    2026: "2026-key-stage-2-scored-conversion-table.md",
}
SUBJECT_HEADINGS = {
    "English grammar, punctuation and spelling": "gps",
    "English reading": "reading",
    "Mathematics": "maths",
}
MAX_MARKS = {"gps": 70, "reading": 50, "maths": 110}

ROW = re.compile(r"^(\d+)(?:\s*-\s*(\d+))?\s+(\d+|No scaled score)$")


class ConversionRow(NamedTuple):
    test_year: int
    ks2_subject: str
    raw_score: int
    scaled_score: int | None


def parse_tables(text: str, test_year: int) -> list[ConversionRow]:
    """Parse one year's markdown page into one row per (subject, raw score)."""
    rows: list[ConversionRow] = []
    subject: str | None = None
    for line in (raw_line.strip() for raw_line in text.splitlines()):
        if line in SUBJECT_HEADINGS:
            subject = SUBJECT_HEADINGS[line]
            continue
        match = ROW.match(line)
        if subject is None or match is None:
            continue
        low, high, scaled = match.groups()
        for raw_score in range(int(low), int(high or low) + 1):
            rows.append(
                ConversionRow(
                    test_year=test_year,
                    ks2_subject=subject,
                    raw_score=raw_score,
                    scaled_score=None if scaled == "No scaled score" else int(scaled),
                )
            )
    return rows


def validate(rows: list[ConversionRow]) -> None:
    """Fail loudly if a table is incomplete or not monotonic."""
    for subject, max_marks in MAX_MARKS.items():
        for year in SOURCES:
            table = sorted(
                (r for r in rows if r.ks2_subject == subject and r.test_year == year),
                key=lambda r: r.raw_score,
            )
            raws = [r.raw_score for r in table]
            if raws != list(range(max_marks + 1)):
                raise ValueError(f"{year} {subject}: raw scores are not 0..{max_marks}")
            scores = [r.scaled_score for r in table if r.scaled_score is not None]
            if scores != sorted(scores) or scores[0] < 80 or scores[-1] != 120:
                raise ValueError(
                    f"{year} {subject}: scaled scores not monotonic 80..120"
                )


def main() -> None:
    rows = [
        row
        for year, name in SOURCES.items()
        for row in parse_tables((ROOT / "reference_docs" / name).read_text(), year)
    ]
    validate(rows)
    rows.sort(key=lambda r: (r.test_year, r.ks2_subject, r.raw_score))
    with SEED.open("w", newline="") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(ConversionRow._fields)
        for row in rows:
            writer.writerow(
                [*row[:3], "" if row.scaled_score is None else row.scaled_score]
            )
    print(f"wrote {len(rows)} rows to {SEED.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
