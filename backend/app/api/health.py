from fastapi import APIRouter

router = APIRouter(tags=["health"])


# Must never touch the database: frequent pings would keep Neon compute awake (SPEC §5.4).
@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
