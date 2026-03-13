from __future__ import annotations

import hashlib
import uuid
from typing import NoReturn

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHash, VerifyMismatchError
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from voxagent.models import AdminRole, AuthContext
from voxagent.queries import (
    get_admin_user,
    get_admin_user_by_email,
    list_tenant_memberships,
    update_admin_user_password,
)

router = APIRouter(prefix="/dashboard")

_COOKIE_NAME = "voxagent_session"
_MAX_AGE_SECONDS = 86400  # 24 hours
_PASSWORD_HASH_VERSION = "argon2id"
_ARGON2 = PasswordHasher()

templates = Jinja2Templates(directory="voxagent/server/templates")


def hash_password(password: str) -> str:
    return _ARGON2.hash(password)


def password_hash_version(password_hash: str) -> str:
    if password_hash.startswith("$argon2id$"):
        return _PASSWORD_HASH_VERSION
    if password_hash.startswith("sha256$"):
        return "sha256"
    if len(password_hash) == 64:
        return "sha256-legacy"
    return "unknown"


def verify_password(password: str, password_hash: str) -> bool:
    version = password_hash_version(password_hash)
    if version == _PASSWORD_HASH_VERSION:
        try:
            return _ARGON2.verify(password_hash, password)
        except (InvalidHash, VerifyMismatchError):
            return False
    legacy_hash = password_hash.removeprefix("sha256$")
    return hashlib.sha256(password.encode()).hexdigest() == legacy_hash


def needs_password_upgrade(password_hash: str) -> bool:
    return password_hash_version(password_hash) != _PASSWORD_HASH_VERSION


def _get_serializer(secret: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(secret, salt="voxagent-session")


@router.get("/login")
async def login_page(request: Request) -> Response:
    return templates.TemplateResponse(request, "login.html")


@router.post("/login")
async def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
) -> Response:
    pool = request.app.state.pool
    admin_user = await get_admin_user_by_email(pool, email)

    if admin_user is None or not admin_user.is_active:
        return templates.TemplateResponse(
            request,
            "login.html",
            context={"error": "Invalid credentials."},
            status_code=401,
        )

    if not verify_password(password, admin_user.password_hash):
        return templates.TemplateResponse(
            request,
            "login.html",
            context={"error": "Invalid credentials."},
            status_code=401,
        )

    if needs_password_upgrade(admin_user.password_hash):
        admin_user = await update_admin_user_password(
            pool=pool,
            admin_user_id=admin_user.id,
            password_hash=hash_password(password),
            password_hash_version=_PASSWORD_HASH_VERSION,
        )

    memberships = await list_tenant_memberships(pool, admin_user.id)
    config = request.app.state.config
    serializer = _get_serializer(config.session_secret)
    token = serializer.dumps(
        {
            "admin_user_id": str(admin_user.id),
            "email": admin_user.email,
            "is_platform_admin": admin_user.is_platform_admin,
            "tenant_roles": {
                str(membership.tenant_id): membership.role.value for membership in memberships
            },
        }
    )

    redirect_url = "/dashboard/tenants" if admin_user.is_platform_admin else "/dashboard/login"
    if memberships:
        redirect_url = f"/dashboard/{memberships[0].tenant_id}/conversations"

    response = RedirectResponse(url=redirect_url, status_code=303)
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


async def require_auth_context(request: Request) -> AuthContext:
    token = request.cookies.get(_COOKIE_NAME)

    if not token:
        _fail_auth(request)

    config = request.app.state.config
    serializer = _get_serializer(config.session_secret)

    try:
        data: dict[str, object] = serializer.loads(token, max_age=_MAX_AGE_SECONDS)
    except (SignatureExpired, BadSignature):
        _fail_auth(request)

    admin_user_id = uuid.UUID(str(data["admin_user_id"]))
    admin_user = await get_admin_user(request.app.state.pool, admin_user_id)
    if admin_user is None or not admin_user.is_active:
        _fail_auth(request)

    tenant_roles_raw = data.get("tenant_roles", {})
    tenant_roles = {
        uuid.UUID(tenant_id): AdminRole(role)
        for tenant_id, role in dict(tenant_roles_raw).items()
    }

    return AuthContext(
        admin_user_id=admin_user.id,
        email=admin_user.email,
        tenant_roles=tenant_roles,
        is_platform_admin=bool(data.get("is_platform_admin", False)),
    )


async def require_platform_admin(
    auth_context: AuthContext = Depends(require_auth_context),
) -> AuthContext:
    if not auth_context.is_platform_admin:
        raise HTTPException(status_code=403, detail="Platform admin access required")
    return auth_context


async def require_auth(request: Request) -> uuid.UUID:
    auth_context = await require_auth_context(request)
    if auth_context.is_platform_admin:
        _fail_auth(request)
    if not auth_context.tenant_roles:
        _fail_auth(request)
    return next(iter(auth_context.tenant_roles))


def _fail_auth(request: Request) -> NoReturn:
    accept = request.headers.get("accept", "")
    if "text/html" in accept:
        raise HTTPException(
            status_code=302,
            headers={"location": "/dashboard/login"},
        )
    raise HTTPException(status_code=401, detail="Not authenticated")
