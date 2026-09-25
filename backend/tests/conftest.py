import os

# Settings are required at import time; unit tests never open this connection.
os.environ.setdefault(
    "DATABASE_URL", "postgresql+psycopg://hakkerja:hakkerja@localhost:5433/hakkerja"
)
