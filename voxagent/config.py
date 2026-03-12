from __future__ import annotations

import os


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if value is None:
        msg = f"Required environment variable {name!r} is not set"
        raise RuntimeError(msg)
    return value


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return int(raw)


class Config:
    """Application configuration loaded from environment variables.

    All required variables raise RuntimeError immediately if missing.
    """

    __slots__ = (
        "database_url",
        "livekit_url",
        "livekit_api_key",
        "livekit_api_secret",
        "ollama_base_url",
        "openai_api_key",
        "elevenlabs_api_key",
        "server_host",
        "server_port",
        "log_level",
    )

    def __init__(self) -> None:
        self.database_url: str = _require_env("DATABASE_URL")
        self.livekit_url: str = _require_env("LIVEKIT_URL")
        self.livekit_api_key: str = _require_env("LIVEKIT_API_KEY")
        self.livekit_api_secret: str = _require_env("LIVEKIT_API_SECRET")

        self.ollama_base_url: str = _env("OLLAMA_BASE_URL", "http://localhost:11434")
        self.openai_api_key: str | None = os.environ.get("OPENAI_API_KEY")
        self.elevenlabs_api_key: str | None = os.environ.get("ELEVENLABS_API_KEY")

        self.server_host: str = _env("SERVER_HOST", "0.0.0.0")
        self.server_port: int = _env_int("SERVER_PORT", 8080)
        self.log_level: str = _env("LOG_LEVEL", "INFO")


def load_config() -> Config:
    return Config()
