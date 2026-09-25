"""Checks the committed data/processed output, so CI validates it without the raw PDFs."""

import pytest

from ingestion.parse_pdf import CATCHWORD_END, HEADER_LINE, SOFT_HYPHEN
from ingestion.sources import Source, load_sources
from ingestion.split_pasal import BODY_END, is_next_number, read_articles, render_ayat

SOURCES = load_sources()


@pytest.mark.parametrize("source", SOURCES, ids=lambda source: source.code)
def test_article_count_and_sequence(source: Source) -> None:
    numbers = [article.article for article in read_articles(source)]

    assert len(numbers) == source.expected_articles
    previous = None
    for number in numbers:
        assert is_next_number(previous, number), f"Pasal {number} follows Pasal {previous}"
        previous = number


@pytest.mark.parametrize("source", SOURCES, ids=lambda source: source.code)
def test_text_matches_ayat(source: Source) -> None:
    for article in read_articles(source):
        if article.ayat:
            assert article.text == render_ayat(article.ayat), f"Pasal {article.article}"
        else:
            assert not article.text.startswith("(1)"), f"Pasal {article.article} lost its ayat"


@pytest.mark.parametrize("source", SOURCES, ids=lambda source: source.code)
def test_no_page_furniture_leaks_into_text(source: Source) -> None:
    for article in read_articles(source):
        assert article.text.strip(), f"Pasal {article.article} is empty"
        lines = [*article.text.splitlines(), *(article.penjelasan or "").splitlines()]
        for line in lines:
            assert not HEADER_LINE.match(line), f"Pasal {article.article}: {line!r}"
            assert not CATCHWORD_END.search(line), f"Pasal {article.article}: {line!r}"
            assert SOFT_HYPHEN not in line
            assert not line.startswith(BODY_END)


@pytest.mark.parametrize("source", SOURCES, ids=lambda source: source.code)
def test_page_spans_are_ordered(source: Source) -> None:
    previous_start = 0
    for article in read_articles(source):
        start, end = article.pages
        assert previous_start <= start <= end, f"Pasal {article.article}: {article.pages}"
        previous_start = start
