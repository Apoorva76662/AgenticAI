"""Agent topology.

    root_agent (LlmAgent, conversational orchestrator)
      ├─ leaf tools: get_employee_profile, get_leave_balance,
      │              get_leave_history, get_public_holidays,
      │              calculate_working_days
      │     -> used directly for narrow queries (balance / history / pure
      │        computation) so those prompts never enter the application flow.
      ├─ AgentTool(prepare_leave_application)
      │     prepare_leave_application = SequentialAgent[
      │         ParallelAgent[ employee_data_agent || calendar_agent ],
      │         calculation_agent
      │     ]
      │     -> the full-application path. The ParallelAgent gives the
      │        demonstrable concurrent Employee + Calendar retrieval.
      └─ FunctionTool(persist_leave_request, require_confirmation=True)
            -> hard human-in-the-loop gate. The DB write cannot run until the
               user confirms in ADK Web.

Why a conversational root instead of a pure SequentialAgent pipeline: the
sample prompts include balance-only, history-only and computation-only
requests that must NOT trigger the application flow. A rigid workflow agent
runs its whole pipeline every turn; an LlmAgent routes.
"""
from __future__ import annotations

import os

from google.adk.agents import LlmAgent, ParallelAgent, SequentialAgent
from google.adk.tools import FunctionTool
from google.adk.tools.agent_tool import AgentTool

from .tools import (
    calculate_working_days,
    get_employee_profile,
    get_leave_balance,
    get_leave_history,
    get_public_holidays,
    persist_leave_request,
)

#MODEL = os.environ.get("LEAVE_MODEL", "gemini-2.5-flash")
# MODEL = os.environ.get("LEAVE_MODEL", "gemini-3.5-flash")
MODEL = os.environ.get("LEAVE_MODEL", "gemini-3.1-flash-lite")


# --------------------------------------------------------------------------- #
# Parallel branch 1: Employee Data Agent                                      #
# --------------------------------------------------------------------------- #
employee_data_agent = LlmAgent(
    name="employee_data_agent",
    model=MODEL,
    description="Retrieves employee profile and leave balance from SQLite.",
    instruction=(
        "You are the Employee Data Agent. The request contains an employee "
        "identifier (an ID like EMP-003 or a full name) and a leave type.\n"
        "1. Call get_employee_profile for that employee.\n"
        "2. Call get_leave_balance for the same employee (and leave type if "
        "given).\n"
        "Then output a compact summary: employee_id, full_name, country_code, "
        "and the relevant balance. Do not ask questions; use only the request."
    ),
    tools=[
        FunctionTool(get_employee_profile),
        FunctionTool(get_leave_balance),
    ],
    output_key="employee_data",
)

# --------------------------------------------------------------------------- #
# Parallel branch 2: Calendar Agent                                           #
# --------------------------------------------------------------------------- #
calendar_agent = LlmAgent(
    name="calendar_agent",
    model=MODEL,
    description="Retrieves the public holiday calendar for the leave window.",
    instruction=(
        "You are the Calendar Agent. The request contains an employee "
        "identifier and a start/end date.\n"
        "Call get_public_holidays with employee=<the identifier>, "
        "start_date=<start>, end_date=<end>. The tool resolves the country "
        "from the employee record itself, so you do NOT need to know the "
        "country first.\n"
        "Output the country_code and the list of holidays in that window."
    ),
    tools=[FunctionTool(get_public_holidays)],
    output_key="holiday_data",
)

# Fan-out: both branches run concurrently (independent given employee+dates).
parallel_data_retrieval = ParallelAgent(
    name="parallel_data_retrieval",
    sub_agents=[employee_data_agent, calendar_agent],
)

# --------------------------------------------------------------------------- #
# Calculation Agent — runs after the fan-out                                  #
# --------------------------------------------------------------------------- #
calculation_agent = LlmAgent(
    name="calculation_agent",
    model=MODEL,
    description="Computes working days for the requested window.",
    instruction=(
        "You are the Leave Calculation Agent. employee_data: {employee_data?} "
        "holiday_data: {holiday_data?}\n"
        "Call calculate_working_days with the employee identifier and the "
        "start_date and end_date from the request. Report the working_days "
        "count and which holidays were excluded."
    ),
    tools=[FunctionTool(calculate_working_days)],
    output_key="calc_result",
)

# Sequential: parallel retrieval -> calculation.
prepare_leave_application = SequentialAgent(
    name="prepare_leave_application",
    sub_agents=[parallel_data_retrieval, calculation_agent],
)

# --------------------------------------------------------------------------- #
# Root orchestrator                                                           #
# --------------------------------------------------------------------------- #
root_agent = LlmAgent(
    name="leave_orchestrator",
    model=MODEL,
    description="Conversational HR leave assistant.",
    instruction=(
        "You are an HR leave-management assistant. Decide intent from the "
        "user's message.\n\n"
        "NARROW QUERIES — use the leaf tools directly, do NOT start an "
        "application:\n"
        "- Balance question -> get_leave_balance.\n"
        "- History question -> get_leave_history (filter by status/year if "
        "asked).\n"
        "- 'How many working days between X and Y [in country C / for "
        "employee E]' -> calculate_working_days. Return the number; stop.\n\n"
        "LEAVE APPLICATION — when the user asks to apply/book/request leave:\n"
        "1. Call the prepare_leave_application tool with a request string that "
        "includes the employee identifier, leave type, start_date and "
        "end_date (ISO YYYY-MM-DD). It runs the employee and calendar lookups "
        "in parallel and returns the working-day calculation.\n"
        "2. Compare working_days against the employee's available balance "
        "(from get_leave_balance if you don't already have it). If "
        "insufficient, explain the shortfall and STOP — do not ask for "
        "confirmation.\n"
        "3. If sufficient, present a confirmation summary with: employee name, "
        "leave type, start date, end date, total working days, and remaining "
        "balance after approval. Ask the user to confirm.\n"
        "4. Only after the user agrees, call persist_leave_request. This tool "
        "requires explicit confirmation before it runs, so no record is "
        "written until then. Report the returned reference number.\n"
        "If the user rejects, discard the request (do not call "
        "persist_leave_request) and offer to modify or restart.\n\n"
        "Dates are inclusive. Never invent balances or holidays — always use "
        "the tools."
    ),
    tools=[
        FunctionTool(get_employee_profile),
        FunctionTool(get_leave_balance),
        FunctionTool(get_leave_history),
        FunctionTool(get_public_holidays),
        FunctionTool(calculate_working_days),
        AgentTool(agent=prepare_leave_application),
        # Hard human-in-the-loop gate: body runs only after user confirmation.
        FunctionTool(persist_leave_request, require_confirmation=True),
    ],
)
