"""Cleaned text in data/interim -> one JSON line per pasal in data/processed/<code>.jsonl."""

import argparse
import json
import logging
import re
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from enum import StrEnum
from itertools import pairwise

from ingestion.parse_pdf import PAGE_SEPARATOR
from ingestion.sources import Source, select_sources

logger = logging.getLogger(__name__)

BAB_HEADING = re.compile(r"^BAB\s+([IVXLCDM]+[A-Z]?)$")
BAGIAN_HEADING = re.compile(r"^Bagian\s+(Pertama|Ke\w+)$")
PARAGRAF_HEADING = re.compile(r"^Paragraf\s+(\d+[A-Z]?)$")
PASAL_HEADING = re.compile(r"^Pasal\s+(\d+[A-Z]?)$")
NUMBER_WITH_SUFFIX = re.compile(r"(\d+)([A-Za-z]?)")
AYAT_START = re.compile(r"^\((\d+[a-z]?)\)\s*(.*)$")

LINE_BREAK_MARKER = re.compile(r"^(\(\d+[a-z]?\)|[a-z]\.|\d{1,2}\.)\s")
# Sub-headings inside the penjelasan ("Ayat (2)", "Huruf a") sit on their own line.
STANDALONE_MARKER = re.compile(r"^(Ayat \(\d+[a-z]?\)|Huruf [a-z]|Angka \d+)$")
# "sebagaimana dimaksud dalam ayat\n(1) ..." is a wrapped reference, not a new ayat.
ENDS_WITH_REFERENCE = re.compile(r"\b(ayat|huruf|angka|pasal)$", re.IGNORECASE)

PENJELASAN_TITLE = ("PENJELASAN", "ATAS")
PENJELASAN_ARTICLES_START = re.compile(r"^II\.\s*PASAL DEMI PASAL$")
BODY_END = "Agar setiap orang mengetahuinya"
PENJELASAN_END = "TAMBAHAN LEMBARAN NEGARA"
NO_EXPLANATION = "cukup jelas"


class ArticleCountMismatchError(Exception):
    pass


class BlockKind(StrEnum):
    BAB = "BAB"
    BAGIAN = "Bagian"
    PARAGRAF = "Paragraf"
    PASAL = "Pasal"


@dataclass(frozen=True, slots=True)
class Line:
    page: int
    text: str


@dataclass(frozen=True, slots=True)
class Block:
    kind: BlockKind
    label: str
    heading_page: int
    lines: tuple[Line, ...]


@dataclass(frozen=True, slots=True)
class Ayat:
    number: str
    text: str


@dataclass(frozen=True, slots=True)
class Article:
    regulation: str
    article: str
    chapter: str | None
    section: str | None
    text: str
    ayat: tuple[Ayat, ...]
    penjelasan: str | None
    pages: tuple[int, int]


def load_lines(text: str) -> list[Line]:
    return [
        Line(page_number, line)
        for page_number, page in enumerate(text.split(PAGE_SEPARATOR), start=1)
        for line in page.splitlines()
        if line
    ]


def split_number(value: str) -> tuple[int, str]:
    match = NUMBER_WITH_SUFFIX.fullmatch(value)
    if match is None:
        raise ValueError(f"not a pasal/ayat number: {value!r}")
    return int(match.group(1)), match.group(2).lower()


def is_next_number(previous: str | None, candidate: str) -> bool:
    """Sequence check for pasal ("88" -> "88A" -> "89") and ayat ("1" -> "1a" -> "2")."""
    if previous is None:
        return candidate == "1"
    previous_number, previous_suffix = split_number(previous)
    number, suffix = split_number(candidate)
    if not suffix:
        return number == previous_number + 1
    expected_suffix = chr(ord(previous_suffix) + 1) if previous_suffix else "a"
    return number == previous_number and suffix == expected_suffix


def split_body_and_penjelasan(lines: list[Line]) -> tuple[list[Line], list[Line]]:
    for index, (line, following) in enumerate(pairwise(lines)):
        if (line.text, following.text) == PENJELASAN_TITLE:
            return lines[:index], lines[index:]
    return lines, []


def slice_between(lines: list[Line], start: re.Pattern[str], end_prefix: str) -> list[Line]:
    start_index = next((i for i, line in enumerate(lines) if start.match(line.text)), len(lines))
    end_index = next(
        (i for i, line in enumerate(lines) if line.text.startswith(end_prefix)), len(lines)
    )
    return lines[start_index:end_index]


def match_structure_heading(text: str) -> tuple[BlockKind, str] | None:
    for kind, pattern in (
        (BlockKind.BAB, BAB_HEADING),
        (BlockKind.BAGIAN, BAGIAN_HEADING),
        (BlockKind.PARAGRAF, PARAGRAF_HEADING),
    ):
        if pattern.match(text):
            return kind, text
    return None


def segment(lines: list[Line]) -> list[Block]:
    """Group lines under their heading. Pasal headings must follow the numbering sequence."""
    blocks: list[tuple[BlockKind, str, int, list[Line]]] = []
    previous_article: str | None = None
    for line in lines:
        heading = match_structure_heading(line.text)
        if pasal := PASAL_HEADING.match(line.text):
            if is_next_number(previous_article, pasal.group(1)):
                heading = BlockKind.PASAL, pasal.group(1)
                previous_article = pasal.group(1)
            else:
                logger.warning(
                    "page %d: %r out of sequence after Pasal %s, kept as text",
                    line.page,
                    line.text,
                    previous_article,
                )
        if heading:
            kind, label = heading
            blocks.append((kind, label, line.page, []))
        elif blocks:
            blocks[-1][3].append(line)
    return [Block(kind, label, page, tuple(body)) for kind, label, page, body in blocks]


def starts_new_line(previous: str | None, text: str) -> bool:
    if previous is None or STANDALONE_MARKER.match(previous) or STANDALONE_MARKER.match(text):
        return True
    return bool(LINE_BREAK_MARKER.match(text)) and not ENDS_WITH_REFERENCE.search(previous)


def join_wrapped_lines(texts: list[str]) -> str:
    """Undo PDF line wrapping, keeping line breaks only before list and ayat markers."""
    texts = [text for text in texts if text]
    parts = [
        ("\n" if starts_new_line(previous, text) else " ") + text
        for previous, text in zip([None, *texts], texts, strict=False)
    ]
    return "".join(parts).lstrip("\n")


def split_ayat(lines: list[Line]) -> tuple[Ayat, ...]:
    groups: list[tuple[str, list[str]]] = []
    previous_text: str | None = None
    for line in lines:
        match = AYAT_START.match(line.text)
        expected = groups[-1][0] if groups else None
        is_reference = previous_text is not None and ENDS_WITH_REFERENCE.search(previous_text)
        if match and is_next_number(expected, match.group(1)) and not is_reference:
            groups.append((match.group(1), [match.group(2)]))
        elif groups:
            groups[-1][1].append(line.text)
        else:
            return ()
        previous_text = line.text
    return tuple(Ayat(number, join_wrapped_lines(texts)) for number, texts in groups)


def render_ayat(ayat: tuple[Ayat, ...]) -> str:
    return "\n".join(f"({item.number}) {item.text}" for item in ayat)


def iter_articles(blocks: list[Block]) -> Iterator[tuple[Block, str | None, str | None]]:
    """Yield each pasal block with its chapter and Bagian/Paragraf path."""
    chapter: str | None = None
    bagian: str | None = None
    paragraf: str | None = None
    for block in blocks:
        title = f"{block.label} - {' '.join(line.text for line in block.lines)}"
        if block.kind is BlockKind.BAB:
            chapter, bagian, paragraf = title, None, None
        elif block.kind is BlockKind.BAGIAN:
            bagian, paragraf = title, None
        elif block.kind is BlockKind.PARAGRAF:
            paragraf = title
        else:
            section = " > ".join(part for part in (bagian, paragraf) if part)
            yield block, chapter, section or None


def build_article(
    source: Source, block: Block, chapter: str | None, section: str | None, penjelasan: str | None
) -> Article:
    body = list(block.lines)
    ayat = split_ayat(body)
    text = render_ayat(ayat) if ayat else join_wrapped_lines([line.text for line in body])
    last_page = body[-1].page if body else block.heading_page
    return Article(
        regulation=source.code,
        article=block.label,
        chapter=chapter,
        section=section,
        text=text,
        ayat=ayat,
        penjelasan=penjelasan,
        pages=(block.heading_page, last_page),
    )


def parse_penjelasan(lines: list[Line]) -> dict[str, str | None]:
    articles = slice_between(lines, PENJELASAN_ARTICLES_START, PENJELASAN_END)[1:]
    explanations: dict[str, str | None] = {}
    for block in segment(articles):
        text = join_wrapped_lines([line.text for line in block.lines])
        explanations[block.label] = None if text.rstrip(".").lower() == NO_EXPLANATION else text
    return explanations


def split_document(source: Source, text: str) -> list[Article]:
    body_lines, penjelasan_lines = split_body_and_penjelasan(load_lines(text))
    first_heading = re.compile(rf"{BAB_HEADING.pattern}|^Pasal 1$")
    body_blocks = segment(slice_between(body_lines, first_heading, BODY_END))
    explanations = parse_penjelasan(penjelasan_lines)
    articles = [
        build_article(source, block, chapter, section, explanations.get(block.label))
        for block, chapter, section in iter_articles(body_blocks)
    ]
    report_unmatched_penjelasan(articles, explanations)
    if len(articles) != source.expected_articles:
        raise ArticleCountMismatchError(
            f"{source.code}: expected {source.expected_articles} pasal, parsed {len(articles)}"
        )
    return articles


def report_unmatched_penjelasan(
    articles: list[Article], explanations: dict[str, str | None]
) -> None:
    article_numbers = {article.article for article in articles}
    for number in explanations.keys() - article_numbers:
        logger.warning("penjelasan for Pasal %s has no matching pasal", number)
    if explanations:
        for number in sorted(article_numbers - explanations.keys(), key=split_number):
            logger.warning("Pasal %s has no penjelasan entry", number)


def write_jsonl(source: Source, articles: list[Article]) -> None:
    source.processed_path.parent.mkdir(parents=True, exist_ok=True)
    rows = (json.dumps(asdict(article), ensure_ascii=False) for article in articles)
    source.processed_path.write_text("\n".join(rows) + "\n", encoding="utf-8", newline="\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--code", help="regulation code, e.g. UU-13-2003")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    for source in select_sources(args.code):
        articles = split_document(source, source.interim_path.read_text(encoding="utf-8"))
        write_jsonl(source, articles)
        logger.info("%s: %d pasal -> %s", source.code, len(articles), source.processed_path)


if __name__ == "__main__":
    main()
