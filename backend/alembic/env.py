from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from app.config import get_settings
from app.db.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


# Sync engine on purpose: psycopg 3 serves the same URL in sync mode, and a one-shot CLI
# gains nothing from async (which would also need a SelectorEventLoop on Windows).
def run_migrations() -> None:
    # Tests point migrations at a throwaway database through config.attributes.
    url = config.attributes.get("database_url") or str(get_settings().database_url)
    engine = create_engine(url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata)
        with context.begin_transaction():
            context.run_migrations()


run_migrations()
