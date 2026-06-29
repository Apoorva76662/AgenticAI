"""
    uv run python runner.py
    # or press F5 / use the debugger; set breakpoints in leave_agent/tools.py

"""
import asyncio
import os

from dotenv import load_dotenv
load_dotenv()
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

# Load GOOGLE_API_KEY from leave_agent/.env before importing the agent.
load_dotenv(os.path.join(os.path.dirname(__file__), "leave_agent", ".env"))

from leave_agent.agent import root_agent  # noqa: E402

APP_NAME = "leave_agent"
USER_ID = "demo-user"

QUERIES = [
    "What is the current leave balance for Sarah Nguyen?",
    "How many working days are there between 23 December 2025 and 2 January "
    "2026 for an employee based in GB?",
    "Show me all approved leave requests for EMP-001 this year.",
]


def _print_event(event) -> None:
    """Surface tool calls, tool results, and final text from an event."""
    content = getattr(event, "content", None)
    if not content or not content.parts:
        return
    for part in content.parts:
        if getattr(part, "function_call", None):
            fc = part.function_call
            print(f"  >> TOOL CALL: {fc.name}({dict(fc.args or {})})")
        elif getattr(part, "function_response", None):
            print(f"  << TOOL RESULT: {part.function_response.name}")
        elif getattr(part, "text", None):
            print(f"  AGENT: {part.text.strip()}")


async def ask(runner: Runner, session_id: str, query: str) -> None:
    print(f"\nUSER: {query}")
    content = types.Content(role="user", parts=[types.Part(text=query)])
    async for event in runner.run_async(
        user_id=USER_ID, session_id=session_id, new_message=content
    ):
        _print_event(event)


async def main() -> None:
    session_service = InMemorySessionService()
    runner = Runner(
        agent=root_agent, app_name=APP_NAME, session_service=session_service
    )
    for query in QUERIES:
        session = await session_service.create_session(
            app_name=APP_NAME, user_id=USER_ID
        )
        await ask(runner, session.id, query)


if __name__ == "__main__":
    asyncio.run(main())
