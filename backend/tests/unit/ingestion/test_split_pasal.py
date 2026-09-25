import logging

import pytest

from app.db.models import RegulationStatus, RegulationType, TextQuality
from ingestion.sources import Source
from ingestion.split_pasal import (
    Article,
    ArticleCountMismatchError,
    is_next_number,
    split_document,
)

PAGE_1 = """UNDANG-UNDANG REPUBLIK INDONESIA
Mengingat : Pasal 5 ayat (1) Undang-Undang Dasar 1945;
BAB I
KETENTUAN UMUM
Pasal 1
Dalam undang-undang ini yang dimaksud dengan:
1. Pekerja adalah setiap orang
yang bekerja.
2. Upah adalah hak pekerja."""

PAGE_2 = """BAB II
PERLINDUNGAN, PENGUPAHAN, DAN
KESEJAHTERAAN
Bagian Kesatu
Umum
Paragraf 1
Waktu Kerja
Pasal 2
(1) Pengusaha wajib membayar upah sebagaimana dimaksud dalam ayat
(2) huruf a.
(2) Ketentuan ini berlaku sebagaimana dimaksud dalam
Pasal 156
untuk semua pekerja."""

PAGE_3 = """BAB III
KETENTUAN PENUTUP
Pasal 3
Undang-undang ini mulai berlaku.
Agar setiap orang mengetahuinya, memerintahkan pengundangan.
Disahkan di Jakarta
PENJELASAN
ATAS
UNDANG-UNDANG
I. UMUM
Pasal 2 dibahas di bagian umum.
II. PASAL DEMI PASAL
Pasal 1
Cukup jelas
Pasal 2
Ayat (1)
Yang dimaksud dengan upah
adalah imbalan.
Ayat (2)
Cukup jelas.
Pasal 3
Cukup jelas.
TAMBAHAN LEMBARAN NEGARA NOMOR 1"""

DOCUMENT = "\f".join([PAGE_1, PAGE_2, PAGE_3])


def make_source(expected_articles: int = 3) -> Source:
    return Source(
        code="UU-1-2000",
        type=RegulationType.UU,
        number="1",
        year=2000,
        title="Contoh",
        enacted_date=None,
        effective_date=None,
        source_url=None,
        status=RegulationStatus.BERLAKU,
        file="UU-1-2000.pdf",
        sha256="0" * 64,
        text_quality=TextQuality.NATIVE,
        expected_articles=expected_articles,
    )


@pytest.fixture
def articles() -> dict[str, Article]:
    return {article.article: article for article in split_document(make_source(), DOCUMENT)}


def test_splits_every_pasal_and_skips_preamble(articles: dict[str, Article]) -> None:
    assert list(articles) == ["1", "2", "3"]


def test_tracks_chapter_and_section(articles: dict[str, Article]) -> None:
    assert articles["1"].chapter == "BAB I - KETENTUAN UMUM"
    assert articles["1"].section is None
    assert articles["2"].chapter == "BAB II - PERLINDUNGAN, PENGUPAHAN, DAN KESEJAHTERAAN"
    assert articles["2"].section == "Bagian Kesatu - Umum > Paragraf 1 - Waktu Kerja"
    assert articles["3"].chapter == "BAB III - KETENTUAN PENUTUP"
    assert articles["3"].section is None


def test_joins_wrapped_lines_but_keeps_list_breaks(articles: dict[str, Article]) -> None:
    assert articles["1"].text == (
        "Dalam undang-undang ini yang dimaksud dengan:\n"
        "1. Pekerja adalah setiap orang yang bekerja.\n"
        "2. Upah adalah hak pekerja."
    )
    assert articles["1"].ayat == ()


def test_wrapped_ayat_reference_is_not_a_new_ayat(articles: dict[str, Article]) -> None:
    ayat = articles["2"].ayat

    assert [item.number for item in ayat] == ["1", "2"]
    assert ayat[0].text == (
        "Pengusaha wajib membayar upah sebagaimana dimaksud dalam ayat (2) huruf a."
    )


def test_out_of_sequence_pasal_heading_stays_in_text(
    articles: dict[str, Article], caplog: pytest.LogCaptureFixture
) -> None:
    assert articles["2"].ayat[1].text == (
        "Ketentuan ini berlaku sebagaimana dimaksud dalam Pasal 156 untuk semua pekerja."
    )
    with caplog.at_level(logging.WARNING):
        split_document(make_source(), DOCUMENT)
    assert "'Pasal 156' out of sequence after Pasal 2" in caplog.text


def test_closing_formula_is_not_part_of_last_pasal(articles: dict[str, Article]) -> None:
    assert articles["3"].text == "Undang-undang ini mulai berlaku."


def test_attaches_penjelasan_and_drops_cukup_jelas(articles: dict[str, Article]) -> None:
    assert articles["1"].penjelasan is None
    assert articles["2"].penjelasan == (
        "Ayat (1)\nYang dimaksud dengan upah adalah imbalan.\nAyat (2)\nCukup jelas."
    )
    assert articles["3"].penjelasan is None


def test_records_page_span(articles: dict[str, Article]) -> None:
    assert articles["1"].pages == (1, 1)
    assert articles["2"].pages == (2, 2)


def test_rejects_unexpected_article_count() -> None:
    with pytest.raises(ArticleCountMismatchError):
        split_document(make_source(expected_articles=4), DOCUMENT)


@pytest.mark.parametrize(
    ("previous", "candidate", "expected"),
    [
        (None, "1", True),
        (None, "2", False),
        ("1", "2", True),
        ("2", "4", False),
        ("88", "88A", True),
        ("88A", "88B", True),
        ("88A", "89", True),
        ("88", "88B", False),
        ("1", "1a", True),
        ("1a", "2", True),
    ],
)
def test_is_next_number(previous: str | None, candidate: str, expected: bool) -> None:
    assert is_next_number(previous, candidate) is expected
