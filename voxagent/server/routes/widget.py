from __future__ import annotations

import uuid

from fastapi import APIRouter, Request
from livekit.api import AccessToken, VideoGrants
from pydantic import BaseModel

router = APIRouter()


class TokenRequest(BaseModel):
    tenant_id: str


class TokenResponse(BaseModel):
    token: str
    room_name: str
    livekit_url: str
    visitor_id: str


@router.post("/api/token", response_model=TokenResponse)
async def create_token(body: TokenRequest, request: Request) -> TokenResponse:
    config = request.app.state.config
    visitor_id = uuid.uuid4()
    room_name = f"{body.tenant_id}_{visitor_id}"

    token = AccessToken(api_key=config.livekit_api_key, api_secret=config.livekit_api_secret)
    token.identity = str(visitor_id)
    token.name = f"visitor-{visitor_id}"
    token.video_grants = VideoGrants(room_join=True, room=room_name)
    jwt_token = token.to_jwt()

    return TokenResponse(
        token=jwt_token,
        room_name=room_name,
        livekit_url=config.livekit_url,
        visitor_id=str(visitor_id),
    )
