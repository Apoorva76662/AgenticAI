# Architecture

```mermaid
flowchart TD
    U([User]) -->|natural language| ROOT[leave_orchestrator<br/>LlmAgent]

    ROOT -->|balance / history / pure computation| LEAF[(Leaf tools:<br/>profile, balance,<br/>history, holidays,<br/>calc working days)]
    ROOT -->|apply for leave| PREP[prepare_leave_application<br/>SequentialAgent]
    ROOT -->|after confirm| PERSIST[persist_leave_request<br/>require_confirmation=TRUE]

    subgraph PREP_FLOW [prepare_leave_application]
        direction TB
        PAR{ParallelAgent}
        PAR --> EDA[employee_data_agent]
        PAR --> CAL[calendar_agent]
        EDA --> CALC[calculation_agent]
        CAL --> CALC
    end
    PREP --> PREP_FLOW

    LEAF <--> DB[(SQLite<br/>leave.db)]
    EDA <--> DB
    CAL <--> DB
    CALC <--> DB
    PERSIST <--> DB

    PERSIST -->|HITL pause| U
```

- **Sequential:** `prepare_leave_application` runs retrieval then calculation in order.
- **Parallel:** `employee_data_agent` and `calendar_agent` run concurrently inside the `ParallelAgent`.
- **Human-in-the-loop:** `persist_leave_request` body executes only after explicit confirmation; the SQLite write lives inside that body.
