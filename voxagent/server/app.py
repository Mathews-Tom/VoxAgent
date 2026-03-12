from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.templating import Jinja2Templates

from voxagent.config import load_config
from voxagent.db import close_pool, init_pool, run_migrations
from voxagent.server.routes.leads import router as leads_router
from voxagent.server.routes.tenants import router as tenants_router
from voxagent.server.routes.widget import router as widget_router

_TEMPLATES_DIR = Path(__file__).parent / "templates"

templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    config = load_config()
    pool = await init_pool(config.database_url)
    await run_migrations(pool)
    app.state.config = config
    app.state.pool = pool

    yield

    await close_pool(pool)


app = FastAPI(title="VoxAgent", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(leads_router)
app.include_router(tenants_router)
app.include_router(widget_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
