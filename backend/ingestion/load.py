"""Processed JSONL -> regulations and provisions tables. Safe to run repeatedly."""

import argparse
import hashlib
import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict
from sqlalchemy import Connection, create_engine, func, select
from sqlalchemy.dialects.postgresql import insert

from app.config import get_settings
from app.db.models import Provision, Regulation
from ingestion.sources import DATA_DIR, Source, select_sources
from ingestion.split_pasal import Article, read_articles

logger = logging.getLogger(__name__)

VERIFIED_FILE = DATA_DIR / "verified_provisions.yaml"
# valid_to and status belong to the consolidation step; a reload must not undo recorded amendments.
LOADER_OWNED_COLUMNS = (
    "label",
    "chapter",
    "section",
    "text",
    "penjelasan",
    "content_sha256",
    "valid_from",
    "verified_manually",
)


class MissingSourceMetadataError(Exception):
    pass


class OrphanProvisionError(Exception):
    pass


class VerifiedProvision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    regulation: str
    article: str
    content_sha256: str


@dataclass(frozen=True, slots=True)
class LoadResult:
    regulation_id: int
    inserted: int
    updated: int


def load_verified(path: Path = VERIFIED_FILE) -> frozenset[VerifiedProvision]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    return frozenset(VerifiedProvision.model_validate(entry) for entry in document["provisions"])


def content_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def citation_name(source: Source) -> str:
    return f"{source.type} {source.number}/{source.year}"


def required_metadata(source: Source) -> tuple[str, date]:
    if source.source_url is None or source.effective_date is None:
        raise MissingSourceMetadataError(
            f"{source.code}: source_url and effective_date are required before loading"
        )
    return source.source_url, source.effective_date


def regulation_values(source: Source) -> dict[str, Any]:
    source_url, effective_date = required_metadata(source)
    return {
        "code": source.code,
        "type": source.type,
        "number": source.number,
        "year": source.year,
        "title": source.title,
        "enacted_date": source.enacted_date,
        "effective_date": effective_date,
        "status": source.status,
        "source_url": source_url,
        "file_sha256": source.sha256,
        "text_quality": source.text_quality,
    }


def provision_values(
    source: Source,
    regulation_id: int,
    article: Article,
    verified: frozenset[VerifiedProvision],
) -> dict[str, Any]:
    _, effective_date = required_metadata(source)
    digest = content_sha256(article.text)
    identity = VerifiedProvision(
        regulation=source.code, article=article.article, content_sha256=digest
    )
    return {
        "regulation_id": regulation_id,
        "article": article.article,
        "label": f"Pasal {article.article} {citation_name(source)}",
        "chapter": article.chapter,
        "section": article.section,
        "text": article.text,
        "penjelasan": article.penjelasan,
        "content_sha256": digest,
        "valid_from": effective_date,
        "verified_manually": identity in verified,
    }


def report_stale_verifications(
    source: Source, rows: list[dict[str, Any]], verified: frozenset[VerifiedProvision]
) -> None:
    current = {row["article"]: row["content_sha256"] for row in rows}
    for entry in verified:
        if entry.regulation != source.code or entry.article not in current:
            continue
        if entry.content_sha256 != current[entry.article]:
            logger.warning(
                "%s Pasal %s: text changed since manual verification, marked unverified",
                source.code,
                entry.article,
            )


def upsert_regulation(connection: Connection, values: dict[str, Any]) -> int:
    statement = insert(Regulation).values(values)
    statement = statement.on_conflict_do_update(
        index_elements=[Regulation.code],
        set_={column: statement.excluded[column] for column in values if column != "code"},
    )
    return connection.execute(statement.returning(Regulation.id)).scalar_one()


def upsert_provisions(connection: Connection, rows: list[dict[str, Any]]) -> None:
    statement = insert(Provision)
    statement = statement.on_conflict_do_update(
        constraint="uq_provisions_version",
        set_={column: statement.excluded[column] for column in LOADER_OWNED_COLUMNS},
    )
    connection.execute(statement, rows)


def check_no_orphans(connection: Connection, regulation_id: int, articles: set[str]) -> None:
    # Rows are never deleted here: answer_citations and /pasal/[id] links point at their ids.
    orphans = connection.scalars(
        select(Provision.article).where(
            Provision.regulation_id == regulation_id,
            Provision.amended_by_id.is_(None),
            Provision.article.not_in(articles),
        )
    ).all()
    if orphans:
        raise OrphanProvisionError(
            f"regulation {regulation_id}: pasal in database but not in processed data: {orphans}"
        )


def count_provisions(connection: Connection, regulation_id: int) -> int:
    return (
        connection.scalar(select(func.count()).where(Provision.regulation_id == regulation_id)) or 0
    )


def load_source(
    connection: Connection,
    source: Source,
    articles: list[Article],
    verified: frozenset[VerifiedProvision],
) -> LoadResult:
    """Upsert one regulation and its original pasal. Run inside a transaction."""
    regulation_id = upsert_regulation(connection, regulation_values(source))
    check_no_orphans(connection, regulation_id, {article.article for article in articles})
    rows = [provision_values(source, regulation_id, article, verified) for article in articles]
    report_stale_verifications(source, rows, verified)
    before = count_provisions(connection, regulation_id)
    upsert_provisions(connection, rows)
    inserted = count_provisions(connection, regulation_id) - before
    return LoadResult(regulation_id, inserted=inserted, updated=len(rows) - inserted)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--code", help="regulation code, e.g. UU-13-2003")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    engine = create_engine(str(get_settings().database_url))
    verified = load_verified()
    for source in select_sources(args.code):
        with engine.begin() as connection:
            result = load_source(connection, source, read_articles(source), verified)
        logger.info(
            "%s: regulation id %d, %d pasal inserted, %d updated",
            source.code,
            result.regulation_id,
            result.inserted,
            result.updated,
        )
    engine.dispose()


if __name__ == "__main__":
    main()
