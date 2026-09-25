from typing import Literal

from pydantic import BaseModel


class PgvectorStatus(BaseModel):
    available: bool
    installed: bool


class DeepHealth(BaseModel):
    status: Literal["ok", "degraded"]
    database: Literal["ok", "unreachable"]
    pgvector: PgvectorStatus | None
