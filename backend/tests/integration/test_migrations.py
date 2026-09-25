from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import URL, Engine, create_engine, insert, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

from app.config import get_settings
from app.db.models import EMBEDDING_DIMENSIONS, Chunk, Provision, Regulation

ALEMBIC_DIR = Path(__file__).resolve().parents[2] / "alembic"
# Downgrading to base wipes every table, so these tests never touch the dev database.
THROWAWAY_DATABASE = "hakkerja_migrations_test"


@pytest.fixture
def database_url() -> Iterator[URL]:
    dev_url = make_url(str(get_settings().database_url))
    admin = create_engine(dev_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f"DROP DATABASE IF EXISTS {THROWAWAY_DATABASE}"))
        connection.execute(text(f"CREATE DATABASE {THROWAWAY_DATABASE}"))

    yield dev_url.set(database=THROWAWAY_DATABASE)

    with admin.connect() as connection:
        connection.execute(text(f"DROP DATABASE {THROWAWAY_DATABASE} WITH (FORCE)"))
    admin.dispose()


@pytest.fixture
def engine(database_url: URL) -> Iterator[Engine]:
    engine = create_engine(database_url)
    yield engine
    engine.dispose()


# Built without alembic.ini so env.py leaves pytest's logging configuration alone.
@pytest.fixture
def alembic_config(database_url: URL) -> Config:
    config = Config()
    config.set_main_option("script_location", str(ALEMBIC_DIR))
    config.attributes["database_url"] = database_url
    return config


def is_vector_installed(engine: Engine) -> bool:
    with engine.connect() as connection:
        return bool(
            connection.scalar(
                text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')")
            )
        )


def insert_regulation(engine: Engine, code: str, number: str, year: int) -> int:
    statement = (
        insert(Regulation)
        .values(
            code=code,
            type="UU",
            number=number,
            year=year,
            title=f"Undang-Undang {number}/{year}",
            source_url=f"https://example.test/{code}.pdf",
        )
        .returning(Regulation.id)
    )
    with engine.begin() as connection:
        return connection.execute(statement).scalar_one()


def insert_provision(engine: Engine, regulation_id: int, **values: object) -> int:
    statement = (
        insert(Provision)
        .values(
            regulation_id=regulation_id,
            article="156",
            label="Pasal 156 UU 13/2003",
            text="Dalam hal terjadi pemutusan hubungan kerja, pengusaha wajib membayar pesangon.",
            content_sha256="0" * 64,
            **values,
        )
        .returning(Provision.id)
    )
    with engine.begin() as connection:
        return connection.execute(statement).scalar_one()


def test_upgrade_downgrade_upgrade_round_trip(alembic_config: Config, engine: Engine) -> None:
    command.upgrade(alembic_config, "head")
    assert "chunks" in inspect(engine).get_table_names()
    assert is_vector_installed(engine)

    command.downgrade(alembic_config, "base")
    assert inspect(engine).get_table_names() == ["alembic_version"]
    assert not is_vector_installed(engine)

    command.upgrade(alembic_config, "head")
    assert "chunks" in inspect(engine).get_table_names()


def test_models_match_migrations(alembic_config: Config) -> None:
    command.upgrade(alembic_config, "head")

    command.check(alembic_config)


def test_amended_article_keeps_original_regulation(alembic_config: Config, engine: Engine) -> None:
    command.upgrade(alembic_config, "head")
    uu_13_2003 = insert_regulation(engine, "UU-13-2003", "13", 2003)
    uu_6_2023 = insert_regulation(engine, "UU-6-2023", "6", 2023)

    insert_provision(
        engine,
        uu_13_2003,
        status="diubah",
        valid_from=date(2003, 3, 25),
        valid_to=date(2023, 3, 31),
    )
    insert_provision(
        engine,
        uu_13_2003,
        amended_by_id=uu_6_2023,
        amendment_ref="Pasal 81 angka 47",
        valid_from=date(2023, 3, 31),
    )

    with pytest.raises(IntegrityError, match="uq_provisions_in_force_article"):
        insert_provision(engine, uu_13_2003, valid_from=date(2024, 1, 1))


def test_chunk_tsv_is_generated_with_indonesian_stemming(
    alembic_config: Config, engine: Engine
) -> None:
    command.upgrade(alembic_config, "head")
    regulation_id = insert_regulation(engine, "UU-13-2003", "13", 2003)
    provision_id = insert_provision(engine, regulation_id, valid_from=date(2003, 3, 25))

    with engine.begin() as connection:
        connection.execute(
            insert(Chunk).values(
                provision_id=provision_id,
                chunk_index=0,
                text="UU 13/2003 Pasal 156 ayat (1): pengusaha wajib membayar pesangon.",
                embedding=[0.1] * EMBEDDING_DIMENSIONS,
                embedding_model="fake",
                corpus_version="test",
            )
        )
        is_match = connection.scalar(
            select(Chunk.tsv.op("@@")(text("to_tsquery('indonesian', 'dibayarkan')")))
        )

    assert is_match is True
