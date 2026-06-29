"""ADK discovers `root_agent` from this package when you run `adk web`."""
from . import agent  # noqa: F401
from .agent import root_agent  # noqa: F401

__all__ = ["root_agent", "agent"]
