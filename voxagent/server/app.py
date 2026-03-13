from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.templating import Jinja2Templates

from voxagent.config import load_config
from voxagent.db import close_pool, init_pool, run_migrations
from voxagent.logging_config import setup_logging
from voxagent.metrics import metrics_response
from voxagent.models import AdminUser
from voxagent.queries import create_admin_user, get_admin_user_by_email
from voxagent.server.auth import hash_password
from voxagent.server.auth import router as auth_router
from voxagent.server.middleware import RateLimitMiddleware
from voxagent.server.routes.analytics import router as analytics_router
from voxagent.server.routes.conversations import router as conversations_router
from voxagent.server.routes.dashboard import router as dashboard_router
from voxagent.server.routes.knowledge import router as knowledge_router
from voxagent.server.routes.leads import router as leads_router
from voxagent.server.routes.tenants import router as tenants_router
from voxagent.server.routes.widget import router as widget_router

_TEMPLATES_DIR = Path(__file__).parent / "templates"

templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    config = load_config()
    setup_logging(config.log_level)
    pool = await init_pool(config.database_url)
    await run_migrations(pool)
    if config.platform_admin_email and config.platform_admin_password:
        existing_admin = await get_admin_user_by_email(pool, config.platform_admin_email)
        if existing_admin is None:
            await create_admin_user(
                pool,
                AdminUser(
                    email=config.platform_admin_email,
                    password_hash=hash_password(config.platform_admin_password),
                    is_platform_admin=True,
                ),
            )
    app.state.config = config
    app.state.pool = pool

    yield

    await close_pool(pool)


app = FastAPI(title="VoxAgent", lifespan=lifespan)

app.add_middleware(RateLimitMiddleware)

app.include_router(analytics_router)
app.include_router(auth_router)
app.include_router(conversations_router)
app.include_router(dashboard_router)
app.include_router(knowledge_router)
app.include_router(leads_router)
app.include_router(tenants_router)
app.include_router(widget_router)


@app.get("/health/live")
async def health_live() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready")
async def health_ready(request: Request) -> dict[str, str]:
    pool = request.app.state.pool
    await pool.fetchval("SELECT 1")
    return {"status": "ready"}


@app.get("/metrics")
async def metrics_endpoint(request: Request) -> Response:
    body, content_type = metrics_response()
    return Response(content=body, media_type=content_type)
