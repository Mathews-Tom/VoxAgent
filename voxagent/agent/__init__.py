from __future__ import annotations

__all__ = ["VoxAgent"]


def __getattr__(name: str) -> object:
    if name == "VoxAgent":
        from voxagent.agent.core import VoxAgent

        return VoxAgent
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
