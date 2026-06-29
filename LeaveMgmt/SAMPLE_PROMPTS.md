# Sample Prompts

---

### 1. Full leave application — Sequential + Parallel + Human-in-the-Loop
> I'd like to apply for annual leave from 14 July 2025 to 25 July 2025 for employee EMP-003.

Expected: orchestrator calls `prepare_leave_application`, which fans out
`employee_data_agent` and `calendar_agent` **concurrently** (visible in the
trace), then `calculation_agent` returns **10 working days** (no GB holiday in
that window). A confirmation summary is shown and the agent waits. On approval,
`persist_leave_request` writes `LR-2025-00xx` and balance drops 17 → 7.

### 2. Balance enquiry — Database Retrieval (no application flow)
> What is the current leave balance for Sarah Nguyen?

Expected: `get_leave_balance` only. Returns ANNUAL 17 and SICK 9 for 2025. No
application flow is started.

### 3. Working-day computation — Computation across boundaries
> How many working days are there between 23 December 2025 and 2 January 2026 for an employee based in GB?

Expected: `calculate_working_days` excludes 25–26 Dec, 1 Jan, and all weekends →
**6 working days**. No application flow.

### 4. Rejection flow — Human-in-the-Loop (no DB write)
> (after the confirmation summary in prompt 1) No, cancel that request. I made an error with the dates.

Expected: the agent does **not** call `persist_leave_request`; no row is written,
no balance changes. It offers to restart or modify.

### 5. Leave history — Database Retrieval
> Show me all approved leave requests for EMP-001 this year.

Expected: `get_leave_history` filtered by status=APPROVED → `LR-2025-0001`,
ANNUAL, 10–14 Feb 2025, 5 working days.

### 6. Insufficient balance — Validation (no confirmation)
> Apply for 30 days of annual leave for EMP-002 starting 1 September 2025.

Expected: computes **22 working days** over the span, compares to EMP-002's
**14** available ANNUAL days, reports the shortfall, and STOPS before any
confirmation.

---

### Extra — Data persistence proof (Scenario 6 trigger)
> Before I apply: how many leave requests does EMP-003 have, and what's the ANNUAL balance?
> (then) Apply for annual leave for EMP-003 from 4 to 8 August 2025. (approve it)
> (then) Now show EMP-003's balance and request count again.

Expected: request count +1, `used_days` up, `available_days` down by the working
days consumed.
