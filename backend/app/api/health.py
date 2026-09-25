from fastapi import APIRouter, Response, status
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app.db.session import SessionDep
from app.schemas.health import DeepHealth, PgvectorStatus

router = APIRouter(tags=["health"])

PGVECTOR_STATUS_SQL = text(
    "SELECT"
    " EXISTS (SELECT 1 FROM pg_available_extensions WHERE name = 'vector'),"
    " EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')"
)


# Must never touch the database: frequent pings would keep Neon compute awake (SPEC §5.4).
@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


# Manual/CI only. Answers 503 so monitors can detect failure from the status code alone.
# "installed" alone does not degrade: the extension is created by the first migration.
@router.get("/health/deep")
async def health_deep(session: SessionDep, response: Response) -> DeepHealth:
    try:
        result = await session.execute(PGVECTOR_STATUS_SQL)
    except OperationalError:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return DeepHealth(status="degraded", database="unreachable", pgvector=None)

    is_available, is_installed = result.one()
    if not is_available:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return DeepHealth(
        status="ok" if is_available else "degraded",
        database="ok",
        pgvector=PgvectorStatus(available=is_available, installed=is_installed),
    )
