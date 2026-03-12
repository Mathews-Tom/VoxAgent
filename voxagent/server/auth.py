from __future__ import annotations

import hashlib
import uuid

from typing import NoReturn

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from voxagent.queries import get_tenant

router = APIRouter(prefix="/dashboard")

_COOKIE_NAME = "voxagent_session"
_MAX_AGE_SECONDS = 86400  # 24 hours

templates = Jinja2Templates(directory="voxagent/server/templates")


def _hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def _get_serializer(secret: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(secret, salt="voxagent-session")


@router.get("/login")
async def login_page(request: Request) -> Response:
    return templates.TemplateResponse(request, "login.html")


@router.post("/login")
async def login(
    request: Request,
    tenant_id: str = Form(...),
    password: str = Form(...),
) -> Response:
    try:
        tenant_uuid = uuid.UUID(tenant_id)
    except ValueError:
        return templates.TemplateResponse(
            request,
            "login.html",
            context={"error": "Invalid tenant ID."},
            status_code=400,
        )

    pool = request.app.state.pool
    tenant = await get_tenant(pool, tenant_uuid)

    if tenant is None or tenant.password_hash is None:
        return templates.TemplateResponse(
            request,
            "login.html",
            context={"error": "Invalid credentials."},
            status_code=401,
        )

    if _hash_password(password) != tenant.password_hash:
        return templates.TemplateResponse(
            request,
            "login.html",
            context={"error": "Invalid credentials."},
            status_code=401,
        )

    config = request.app.state.config
    serializer = _get_serializer(config.session_secret)
    token = serializer.dumps({"tenant_id": str(tenant_uuid)})

    response = RedirectResponse(
        url=f"/dashboard/{tenant_uuid}/conversations", status_code=303
    )
    response.set_cookie(
        key=_COOKIE_NAME,
        value=token,
        max_age=_MAX_AGE_SECONDS,
        httponly=True,
        samesite="lax",
    )
    return response


@router.post("/logout")
async def logout() -> RedirectResponse:
    response = RedirectResponse(url="/dashboard/login", status_code=303)
    response.delete_cookie(key=_COOKIE_NAME)
    return response


async def require_auth(request: Request) -> uuid.UUID:
    token = request.cookies.get(_COOKIE_NAME)

    if not token:
        _fail_auth(request)

    config = request.app.state.config
    serializer = _get_serializer(config.session_secret)

    try:
        data: dict[str, str] = serializer.loads(token, max_age=_MAX_AGE_SECONDS)
    except (SignatureExpired, BadSignature):
        _fail_auth(request)

    return uuid.UUID(data["tenant_id"])


def _fail_auth(request: Request) -> NoReturn:
    # Browser requests (Accept: text/html) get a redirect; API clients get 401.
    accept = request.headers.get("accept", "")
    if "text/html" in accept:
        raise HTTPException(
            status_code=302,
            headers={"location": "/dashboard/login"},
        )
    raise HTTPException(status_code=401, detail="Not authenticated")
