# Employee Leave Management — Multi-Agent System (Google ADK)

Conversational multi-agent system that automates employee leave applications.
Built on **Google ADK** and demonstrated locally through ADK's own web UI
(`adk web`).

> **Framework choice: GCP / Google ADK.** Chosen because ADK ships a local agent
> web UI with a built-in trace panel, native `SequentialAgent` / `ParallelAgent`
> orchestration primitives, and a first-class human-in-the-loop primitive
> (`require_confirmation`). ADK is open source (Apache 2.0); the
> only hosted dependency is the Gemini model, called via an API key.

## Architecture

```
root_agent (LlmAgent, conversational orchestrator)
  ├─ leaf tools  -> get_employee_profile, get_leave_balance, get_leave_history,
  │                 get_public_holidays, calculate_working_days
  │                 (balance / history / pure-computation prompts use these)
  ├─ AgentTool(prepare_leave_application)         <- full application flow
  │     SequentialAgent[
  │        ParallelAgent[ employee_data_agent || calendar_agent ],   <- concurrent
  │        calculation_agent
  │     ]
  └─ FunctionTool(persist_leave_request, require_confirmation=True)   <- HITL gate
```

Diagram: `docs/architecture.md`.

### Two design decisions worth reading

1. **The root is a conversational `LlmAgent`** Several
   sample prompts (balance enquiry, history, pure working-day computation) must
   NOT enter the application flow. A `SequentialAgent` pipeline runs end-to-end
   every turn; an `LlmAgent` routes by intent and invokes the application
   pipeline only when the user actually applies for leave.

2. **The parallel retrieval is independent.** The holiday calendar
   depends on the employee's `country_code`, which lives on the employee record —
   so a naive split is not independent. The Calendar tool therefore resolves the
   country from `employee_id` itself, so the Employee and Calendar branches need
   only `employee_id` + dates and run concurrently for real, not just on paper.

## Prerequisites

- Python 3.12+
- [`uv`](https://docs.astral.sh/uv/)
- A Gemini API key from [Google AI Studio](https://aistudio.google.com/apikey)

## Run it (under 5 minutes)

```bash
# 1. install from the committed lockfile
uv sync

# 2. add the model key
cat > leave_agent/.env <<'EOF'
GOOGLE_GENAI_USE_VERTEXAI=FALSE
GOOGLE_API_KEY=your_ai_studio_key_here
EOF

# 3. (optional) seed the database — it also self-initialises on first use
uv run python -m leave_agent.database

# 4. launch ADK's web UI, then open the printed localhost URL
uv run adk web
```

In the UI, select the **leave_agent** app and start chatting. Use the
**Events / trace panel** to observe sequential and parallel tool calls and the
confirmation pause.

```bash
uv run python runner.py
```

`runner.py` fires the read-path prompts and prints each tool call + result —
handy for debugging with breakpoints in `leave_agent/tools.py`. The full
apply→confirm flow is best shown in `adk web`, where the confirmation control
lives.

## Environment variables

| Variable                    | Purpose                                      |
|-----------------------------|----------------------------------------------|
| `GOOGLE_API_KEY`            | Gemini API key (Google AI Studio)            |
| `GOOGLE_GENAI_USE_VERTEXAI` | `FALSE` for AI Studio                        |
| `LEAVE_MODEL`               | Override model (default `gemini-2.5-flash`)  |
| `LEAVE_DB_PATH`             | Override SQLite file location                |

## Human-in-the-loop behaviour

`persist_leave_request` is wrapped with `require_confirmation=True`. ADK pauses
**before the tool body executes** and surfaces a confirmation control in the web
UI. The SQLite write is inside that body, so **no row is written and no balance
changes until you confirm**. Rejecting leaves the database untouched.

## Demonstration mapping

See `SAMPLE_PROMPTS.md`. The six prompts map to: sequential execution, parallel
execution, human-in-the-loop (approve + reject), database retrieval, working-day
computation across boundaries, and data persistence with balance updates.

## Known limitations

- Manager approval, notifications, auth, and live calendar sync are out of scope
  per the brief.
- Holiday data is a static seed table for IN and GB, 2025–2026.
- SQLite is a local file (the brief mandates SQLite). The DB self-initialises if
  missing. `uv.lock` is committed for reproducible installs.

## Project layout

```
leave-management-agent/
├── pyproject.toml          # UV manifest (no requirements.txt)
├── uv.lock                 # committed lockfile
├── runner.py               # optional terminal runner / debugger entry
├── README.md
├── SAMPLE_PROMPTS.md
├── docs/architecture.md    # mermaid diagram
└── leave_agent/            # the ADK app (adk web discovers root_agent here)
    ├── __init__.py
    ├── agent.py            # orchestrator + sub-agents + parallel pipeline
    ├── tools.py            # DB tools, working-day logic, confirmed write
    └── database.py         # schema + idempotent seed (run with -m)
```
