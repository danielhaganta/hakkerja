"""Checks the committed data/processed output, so CI validates it without the raw PDFs."""

import json
from typing import Any

import pytest

from ingestion.parse_pdf import CATCHWORD_END, HEADER_LINE, SOFT_HYPHEN
from ingestion.sources import Source, load_sources
from ingestion.split_pasal import BODY_END, Ayat, is_next_number, render_ayat

SOURCES = load_sources()


def read_rows(source: Source) -> list[dict[str, Any]]:
    lines = source.processed_path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines]


@pytest.mark.parametrize("source", SOURCES, ids=lambda source: source.code)
def test_article_count_and_sequence(source: Source) -> None:
    numbers = [row["article"] for row in read_rows(source)]

    assert len(numbers) == source.expected_articles
    previous = None
    for number in numbers:
        assert is_next_number(previous, number), f"Pasal {number} follows Pasal {previous}"
        previous = number


@pytest.mark.parametrize("source", SOURCES, ids=lambda source: source.code)
def test_text_matches_ayat(source: Source) -> None:
    for row in read_rows(source):
        ayat = tuple(Ayat(**item) for item in row["ayat"])
        if ayat:
            assert row["text"] == render_ayat(ayat), f"Pasal {row['article']}"
        else:
            assert not row["text"].startswith("(1)"), f"Pasal {row['article']} lost its ayat"


@pytest.mark.parametrize("source", SOURCES, ids=lambda source: source.code)
def test_no_page_furniture_leaks_into_text(source: Source) -> None:
    for row in read_rows(source):
        assert row["text"].strip(), f"Pasal {row['article']} is empty"
        lines = [*row["text"].splitlines(), *(row["penjelasan"] or "").splitlines()]
        for line in lines:
            assert not HEADER_LINE.match(line), f"Pasal {row['article']}: {line!r}"
            assert not CATCHWORD_END.search(line), f"Pasal {row['article']}: {line!r}"
            assert SOFT_HYPHEN not in line
            assert not line.startswith(BODY_END)


@pytest.mark.parametrize("source", SOURCES, ids=lambda source: source.code)
def test_page_spans_are_ordered(source: Source) -> None:
    previous_start = 0
    for row in read_rows(source):
        start, end = row["pages"]
        assert previous_start <= start <= end, f"Pasal {row['article']}: {row['pages']}"
        previous_start = start
