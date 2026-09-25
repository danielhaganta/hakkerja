import asyncio
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import URL, Engine, create_engine, text
from sqlalchemy.engine import make_url

from app.config import get_settings
from app.main import app

ALEMBIC_DIR = Path(__file__).resolve().parents[2] / "alembic"
# Migration tests downgrade to base and loader tests write rows; keep both off the dev database.
THROWAWAY_DATABASE = "hakkerja_integration_test"


# psycopg async cannot run on Windows' default ProactorEventLoop.
@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app, backend_options={"loop_factory": asyncio.SelectorEventLoop}) as client:
        yield client


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


@pytest.fixture
def migrated_engine(alembic_config: Config, engine: Engine) -> Engine:
    command.upgrade(alembic_config, "head")
    return engine
