import logging
from dataclasses import replace
from datetime import date

import pytest
from sqlalchemy import Engine, Row, func, select, update

from app.db.models import Provision, Regulation, RegulationStatus, RegulationType, TextQuality
from ingestion.load import (
    LoadResult,
    OrphanProvisionError,
    VerifiedProvision,
    content_sha256,
    load_source,
)
from ingestion.sources import Source, load_sources
from ingestion.split_pasal import Article, read_articles

SOURCE = Source(
    code="UU-13-2003",
    type=RegulationType.UU,
    number="13",
    year=2003,
    title="Ketenagakerjaan",
    enacted_date=date(2003, 3, 25),
    effective_date=date(2003, 3, 25),
    source_url="https://example.test/uu-13-2003",
    status=RegulationStatus.DIUBAH_SEBAGIAN,
    file="UU-13-2003.pdf",
    sha256="a" * 64,
    text_quality=TextQuality.NATIVE,
    expected_articles=2,
)


def make_article(number: str, text: str) -> Article:
    return Article(
        regulation="UU-13-2003",
        article=number,
        chapter="BAB I - KETENTUAN UMUM",
        section=None,
        text=text,
        ayat=(),
        penjelasan=None,
        pages=(1, 1),
    )


ARTICLES = [
    make_article("1", "Dalam undang-undang ini yang dimaksud dengan pekerja."),
    make_article("2", "Pembangunan ketenagakerjaan berlandaskan Pancasila."),
]


def load(
    engine: Engine,
    articles: list[Article],
    verified: frozenset[VerifiedProvision] = frozenset(),
    source: Source = SOURCE,
) -> LoadResult:
    with engine.begin() as connection:
        return load_source(connection, source, articles, verified)


def provision_rows(engine: Engine) -> list[Row[tuple[int, str, str, str, date | None, str, bool]]]:
    statement = select(
        Provision.id,
        Provision.article,
        Provision.text,
        Provision.content_sha256,
        Provision.valid_to,
        Provision.status,
        Provision.verified_manually,
    ).order_by(Provision.id)
    with engine.connect() as connection:
        return list(connection.execute(statement).all())


def count(engine: Engine, model: type[Regulation] | type[Provision]) -> int:
    with engine.connect() as connection:
        return connection.scalar(select(func.count()).select_from(model)) or 0


def test_loading_twice_keeps_row_counts_and_ids(migrated_engine: Engine) -> None:
    first = load(migrated_engine, ARTICLES)
    ids_after_first = [row.id for row in provision_rows(migrated_engine)]

    second = load(migrated_engine, ARTICLES)

    assert (first.inserted, first.updated) == (2, 0)
    assert (second.inserted, second.updated) == (0, 2)
    assert second.regulation_id == first.regulation_id
    assert count(migrated_engine, Regulation) == 1
    assert count(migrated_engine, Provision) == 2
    assert [row.id for row in provision_rows(migrated_engine)] == ids_after_first


def test_reload_updates_changed_text_in_place(migrated_engine: Engine) -> None:
    load(migrated_engine, ARTICLES)
    before = provision_rows(migrated_engine)[1]
    edited = replace(ARTICLES[1], text="Pembangunan ketenagakerjaan berlandaskan UUD 1945.")

    load(migrated_engine, [ARTICLES[0], edited])

    after = provision_rows(migrated_engine)[1]
    assert after.id == before.id
    assert after.text == edited.text
    assert after.content_sha256 == content_sha256(edited.text) != before.content_sha256


def test_reload_keeps_columns_owned_by_consolidation(migrated_engine: Engine) -> None:
    load(migrated_engine, ARTICLES)
    with migrated_engine.begin() as connection:
        connection.execute(
            update(Provision)
            .where(Provision.article == "2")
            .values(valid_to=date(2023, 3, 31), status="diubah")
        )

    load(migrated_engine, ARTICLES)

    row = provision_rows(migrated_engine)[1]
    assert (row.valid_to, row.status) == (date(2023, 3, 31), "diubah")


def test_orphan_provision_aborts_the_whole_load(migrated_engine: Engine) -> None:
    load(migrated_engine, ARTICLES)
    edited_first = replace(ARTICLES[0], text="Teks yang tidak boleh tersimpan.")

    with pytest.raises(OrphanProvisionError, match=r"\['2'\]"):
        load(migrated_engine, [edited_first])

    assert provision_rows(migrated_engine)[0].text == ARTICLES[0].text


def test_verified_manually_follows_content_hash(
    migrated_engine: Engine, caplog: pytest.LogCaptureFixture
) -> None:
    checked = VerifiedProvision(
        regulation="UU-13-2003", article="1", content_sha256=content_sha256(ARTICLES[0].text)
    )
    load(migrated_engine, ARTICLES, frozenset({checked}))
    assert [row.verified_manually for row in provision_rows(migrated_engine)] == [True, False]

    edited_first = replace(ARTICLES[0], text="Teks pasal 1 yang berubah setelah diverifikasi.")
    with caplog.at_level(logging.WARNING):
        load(migrated_engine, [edited_first, ARTICLES[1]], frozenset({checked}))

    assert [row.verified_manually for row in provision_rows(migrated_engine)] == [False, False]
    assert "UU-13-2003 Pasal 1: text changed since manual verification" in caplog.text


def test_loads_committed_uu13_data(migrated_engine: Engine) -> None:
    source = next(source for source in load_sources() if source.code == "UU-13-2003")

    result = load(migrated_engine, read_articles(source), source=source)

    assert result.inserted == source.expected_articles
    with migrated_engine.connect() as connection:
        chapter = connection.scalar(select(Provision.chapter).where(Provision.article == "156"))
    assert chapter == "BAB XII - PEMUTUSAN HUBUNGAN KERJA"
