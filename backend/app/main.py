from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import health
from app.db.session import engine


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    yield
    await engine.dispose()


app = FastAPI(title="HakKerja API", version="0.1.0", lifespan=lifespan)
app.include_router(health.router)
