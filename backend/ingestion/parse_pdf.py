"""PDF -> cleaned page text in data/interim/<code>.txt, pages separated by form feeds."""

import argparse
import hashlib
import logging
import re
from collections.abc import Callable
from enum import StrEnum
from pathlib import Path

import pypdfium2 as pdfium

from ingestion.sources import Source, select_sources

logger = logging.getLogger(__name__)

PAGE_SEPARATOR = "\f"
# PDFium marks a line-end hyphen with U+FFFE and joins the two halves onto one line.
SOFT_HYPHEN = "￾"
MAX_HEADER_LINES = 4
# "PRESIDEN" / "REPUBLIK INDONESIA" / "- 12 -", loose enough for OCR variants like "PRESTDEN".
HEADER_LINE = re.compile(r"^(PRES\S*|RE\S*\s+INDONESIA|-\s*\d+\s*-)$")
# The last line of a page repeats the start of the next page, ending in an ellipsis.
CATCHWORD_END = re.compile(r"(\.\s?\.\s?\.|…)$")
SOFT_HYPHEN_SITE = re.compile(rf"(\w+){SOFT_HYPHEN}(\w+)")
MIN_SHARED_STEM = 3


class ChecksumMismatchError(Exception):
    pass


class HyphenEvidence(StrEnum):
    FREQUENCY = "frequency"
    REDUPLICATION = "reduplication"
    NONE = "none"


def read_page_texts(path: Path) -> list[str]:
    document = pdfium.PdfDocument(path)
    return [page.get_textpage().get_text_range() for page in document]


def verify_checksum(source: Source) -> None:
    with source.raw_path.open("rb") as file:
        actual = hashlib.file_digest(file, "sha256").hexdigest()
    if actual != source.sha256:
        raise ChecksumMismatchError(f"{source.file}: expected {source.sha256}, got {actual}")


def clean_page(text: str) -> list[str]:
    lines = [" ".join(line.replace("\xa0", " ").split()) for line in text.splitlines()]
    lines = [line for line in lines if line]
    header_end = 0
    while header_end < min(MAX_HEADER_LINES, len(lines)) and HEADER_LINE.match(lines[header_end]):
        header_end += 1
    lines = lines[header_end:]
    if lines and CATCHWORD_END.search(lines[-1]):
        lines = lines[:-1]
    return lines


def shares_stem(left: str, right: str) -> bool:
    """True for reduplication such as undang-undang, sewenang-wenang, sebaik-baiknya."""
    left, right = left.lower(), right.lower()
    longest = min(len(left), len(right))
    return any(left.endswith(right[:size]) for size in range(MIN_SHARED_STEM, longest + 1))


def resolve_soft_hyphen(left: str, right: str, document_text: str) -> tuple[str, HyphenEvidence]:
    """Return the joiner ("-" or "") for a line-end hyphen and what the choice is based on.

    Prefer how the same word is written elsewhere in the document; fall back to
    reduplication, and otherwise treat it as plain syllable hyphenation.
    """
    hyphenated = count_word(f"{left}-{right}", document_text)
    joined = count_word(f"{left}{right}", document_text)
    if hyphenated != joined:
        return ("-" if hyphenated > joined else ""), HyphenEvidence.FREQUENCY
    if shares_stem(left, right):
        return "-", HyphenEvidence.REDUPLICATION
    return "", HyphenEvidence.NONE


def count_word(word: str, text: str) -> int:
    return len(re.findall(rf"\b{re.escape(word)}\b", text, flags=re.IGNORECASE))


def resolve_soft_hyphens(pages: list[list[str]]) -> list[list[str]]:
    document_text = "\n".join(line for lines in pages for line in lines)

    def replace(match: re.Match[str]) -> str:
        left, right = match.groups()
        joiner, evidence = resolve_soft_hyphen(left, right, document_text)
        if evidence is HyphenEvidence.NONE:
            logger.warning("ambiguous hyphenation %s|%s -> %s", left, right, left + right)
        return f"{left}{joiner}{right}"

    return [[apply_to_line(line, replace) for line in lines] for lines in pages]


def apply_to_line(line: str, replace: Callable[[re.Match[str]], str]) -> str:
    resolved = SOFT_HYPHEN_SITE.sub(replace, line)
    if SOFT_HYPHEN in resolved:
        logger.warning("stray soft hyphen removed: %r", resolved)
        resolved = resolved.replace(SOFT_HYPHEN, "")
    return resolved


def extract_clean_pages(path: Path) -> list[list[str]]:
    pages = [clean_page(text) for text in read_page_texts(path)]
    return resolve_soft_hyphens(pages)


def write_interim(source: Source, pages: list[list[str]]) -> None:
    source.interim_path.parent.mkdir(parents=True, exist_ok=True)
    text = PAGE_SEPARATOR.join("\n".join(lines) for lines in pages)
    source.interim_path.write_text(text, encoding="utf-8", newline="\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--code", help="regulation code, e.g. UU-13-2003")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    for source in select_sources(args.code):
        verify_checksum(source)
        pages = extract_clean_pages(source.raw_path)
        write_interim(source, pages)
        logger.info("%s: %d pages -> %s", source.code, len(pages), source.interim_path)


if __name__ == "__main__":
    main()
