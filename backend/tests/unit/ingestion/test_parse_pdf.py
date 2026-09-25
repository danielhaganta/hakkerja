import logging

import pytest

from ingestion.parse_pdf import (
    SOFT_HYPHEN,
    HyphenEvidence,
    clean_page,
    resolve_soft_hyphen,
    resolve_soft_hyphens,
)


def test_clean_page_drops_header_including_ocr_variants() -> None:
    page = "PRESTDEN\r\nREPUELIK INDONESIA\r\n-7 -\r\nPasal 5\r\nSetiap tenaga kerja"

    assert clean_page(page) == ["Pasal 5", "Setiap tenaga kerja"]


def test_clean_page_keeps_header_like_text_below_the_top() -> None:
    page = "Disahkan di Jakarta\npada tanggal 25 Maret 2003\nPRESIDEN REPUBLIK INDONESIA,"

    assert clean_page(page) == page.splitlines()


@pytest.mark.parametrize("catchword", ["Pasal 12 ...", "b. uang . . .", "BAB XIII …"])
def test_clean_page_drops_trailing_catchword(catchword: str) -> None:
    last_line = "(4) Ketentuan lebih lanjut."

    assert clean_page(f"{last_line}\n{catchword}") == [last_line]


def test_clean_page_normalizes_whitespace() -> None:
    assert clean_page("upah\xa0 minimum   provinsi\n\n") == ["upah minimum provinsi"]


@pytest.mark.parametrize(
    ("left", "right", "document", "expected", "evidence"),
    [
        ("sewenang", "wenang", "", "sewenang-wenang", HyphenEvidence.REDUPLICATION),
        ("bermacam", "macam", "", "bermacam-macam", HyphenEvidence.REDUPLICATION),
        ("sebaik", "baiknya", "", "sebaik-baiknya", HyphenEvidence.REDUPLICATION),
        ("undang", "undang", "peraturan perundang-undangan dan undang-undang", "undang-undang",
         HyphenEvidence.FREQUENCY),
        ("Ketenaga", "kerjaan", "di bidang ketenagakerjaan", "Ketenagakerjaan",
         HyphenEvidence.FREQUENCY),
        ("Ketenaga", "kerjaan", "", "Ketenagakerjaan", HyphenEvidence.NONE),
        ("terus", "menerus", "secara terus-menerus", "terus-menerus", HyphenEvidence.FREQUENCY),
    ],
)  # fmt: skip
def test_resolve_soft_hyphen(
    left: str, right: str, document: str, expected: str, evidence: HyphenEvidence
) -> None:
    joiner, actual_evidence = resolve_soft_hyphen(left, right, document)

    assert f"{left}{joiner}{right}" == expected
    assert actual_evidence is evidence


def test_resolve_soft_hyphens_logs_only_unsupported_guesses(
    caplog: pytest.LogCaptureFixture,
) -> None:
    pages = [[f"secara terus{SOFT_HYPHEN}menerus dan undang{SOFT_HYPHEN}undang"]]

    with caplog.at_level(logging.WARNING):
        resolved = resolve_soft_hyphens(pages)

    assert resolved == [["secara terusmenerus dan undang-undang"]]
    assert [record.getMessage() for record in caplog.records] == [
        "ambiguous hyphenation terus|menerus -> terusmenerus"
    ]
