
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from .database import get_connection, now_iso


# --------------------------------------------------------------------------- #
# The "Leave Calculation Agent" core.                            #
# --------------------------------------------------------------------------- #
def count_working_days(start: str, end: str, holiday_dates: list[str]) -> int:
    """Inclusive working days between start and end (YYYY-MM-DD strings),
    excluding Saturdays, Sundays, and any date in holiday_dates.

    Correct across month and year boundaries.
    """
    d0 = date.fromisoformat(start)
    d1 = date.fromisoformat(end)
    if d1 < d0:
        raise ValueError("end_date is before start_date")
    holidays = set(holiday_dates)
    days = 0
    cur = d0
    while cur <= d1:
        if cur.weekday() < 5 and cur.isoformat() not in holidays:  # 0=Mon..4=Fri
            days += 1
        cur += timedelta(days=1)
    return days


# --------------------------------------------------------------------------- #
# Employee Data tools                                                          #
# --------------------------------------------------------------------------- #
def _resolve_employee(cur, identifier: str):
    """Look up by employee_id first, then by (case-insensitive) full_name."""
    row = cur.execute(
        "SELECT * FROM employees WHERE employee_id = ?", (identifier,)
    ).fetchone()
    if row:
        return row
    return cur.execute(
        "SELECT * FROM employees WHERE LOWER(full_name) = LOWER(?)", (identifier,)
    ).fetchone()


def get_employee_profile(employee: str) -> dict:
    """Fetch an employee profile by employee_id (e.g. 'EMP-003') or full name."""
    conn = get_connection()
    try:
        row = _resolve_employee(conn.cursor(), employee)
        if not row:
            return {"found": False, "error": f"No employee matched '{employee}'."}
        return {"found": True, **dict(row)}
    finally:
        conn.close()


def get_leave_balance(employee: str, year: Optional[int] = None,
                      leave_type: Optional[str] = None) -> dict:
    """Current leave balance(s) for an employee. Optionally filter by year and
    leave_type (ANNUAL/SICK/PERSONAL)."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        emp = _resolve_employee(cur, employee)
        if not emp:
            return {"found": False, "error": f"No employee matched '{employee}'."}
        q = "SELECT leave_type, year, total_days, used_days, available_days " \
            "FROM leave_balances WHERE employee_id = ?"
        params: list = [emp["employee_id"]]
        if year is not None:
            q += " AND year = ?"; params.append(year)
        if leave_type is not None:
            q += " AND leave_type = ?"; params.append(leave_type.upper())
        balances = [dict(r) for r in cur.execute(q, params).fetchall()]
        return {
            "found": True,
            "employee_id": emp["employee_id"],
            "full_name": emp["full_name"],
            "balances": balances,
        }
    finally:
        conn.close()


def get_leave_history(employee: str, status: Optional[str] = None,
                     year: Optional[int] = None) -> dict:
    """Leave request history for an employee. Optionally filter by status
    (APPROVED/PENDING/REJECTED/CANCELLED) and year."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        emp = _resolve_employee(cur, employee)
        if not emp:
            return {"found": False, "error": f"No employee matched '{employee}'."}
        q = "SELECT request_id, leave_type, start_date, end_date, working_days, " \
            "status, submitted_at, notes FROM leave_requests WHERE employee_id = ?"
        params: list = [emp["employee_id"]]
        if status is not None:
            q += " AND status = ?"; params.append(status.upper())
        if year is not None:
            q += " AND substr(start_date,1,4) = ?"; params.append(str(year))
        q += " ORDER BY start_date DESC"
        rows = [dict(r) for r in cur.execute(q, params).fetchall()]
        return {"found": True, "employee_id": emp["employee_id"], "requests": rows}
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Calendar tool                                                               #
# --------------------------------------------------------------------------- #
def get_public_holidays(country_code: Optional[str] = None,
                        employee: Optional[str] = None,
                        start_date: Optional[str] = None,
                        end_date: Optional[str] = None) -> dict:
    """Public holidays for a country. Provide either country_code OR an employee
    (id/name) — if an employee is given, the country is resolved from their
    record, which keeps this independent of the employee-data branch.

    Optionally bound the result to a [start_date, end_date] window.
    """
    conn = get_connection()
    try:
        cur = conn.cursor()
        if not country_code:
            if not employee:
                return {"error": "Provide country_code or employee."}
            emp = _resolve_employee(cur, employee)
            if not emp:
                return {"error": f"No employee matched '{employee}'."}
            country_code = emp["country_code"]
        country_code = country_code.upper()
        q = "SELECT holiday_date, holiday_name FROM public_holidays " \
            "WHERE country_code = ?"
        params: list = [country_code]
        if start_date:
            q += " AND holiday_date >= ?"; params.append(start_date)
        if end_date:
            q += " AND holiday_date <= ?"; params.append(end_date)
        q += " ORDER BY holiday_date"
        rows = [dict(r) for r in cur.execute(q, params).fetchall()]
        return {"country_code": country_code, "holidays": rows}
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Calculation tool (wraps the pure function; self-contained for robustness)   #
# --------------------------------------------------------------------------- #
def calculate_working_days(start_date: str, end_date: str,
                           country_code: Optional[str] = None,
                           employee: Optional[str] = None) -> dict:
    """Working days in [start_date, end_date] inclusive, excluding weekends and
    that country's public holidays. Country resolved from country_code or the
    employee's record. Returns the count and the specific holidays excluded."""
    hol = get_public_holidays(
        country_code=country_code, employee=employee,
        start_date=start_date, end_date=end_date,
    )
    if "error" in hol:
        return hol
    holiday_dates = [h["holiday_date"] for h in hol["holidays"]]
    try:
        wd = count_working_days(start_date, end_date, holiday_dates)
    except ValueError as e:
        return {"error": str(e)}
    return {
        "start_date": start_date,
        "end_date": end_date,
        "country_code": hol["country_code"],
        "working_days": wd,
        "holidays_excluded": hol["holidays"],
    }


# --------------------------------------------------------------------------- #
# Persistence tool — HARD human-in-the-loop gate (require_confirmation=True).  #
# The body below does NOT run until the user confirms in ADK Web, so no row is #
# ever written before approval.                                               #
# --------------------------------------------------------------------------- #
def _next_request_id(cur, year: int) -> str:
    prefix = f"LR-{year}-"
    row = cur.execute(
        "SELECT request_id FROM leave_requests WHERE request_id LIKE ? "
        "ORDER BY request_id DESC LIMIT 1",
        (prefix + "%",),
    ).fetchone()
    nxt = (int(row["request_id"].split("-")[-1]) + 1) if row else 1
    return f"{prefix}{nxt:04d}"


def persist_leave_request(employee: str, leave_type: str,
                          start_date: str, end_date: str,
                          notes: str = "") -> dict:
    """Validate and persist an APPROVED leave request, then decrement the
    balance. Recomputes working days server-side and re-checks the balance as a
    guard. Returns the new reference id and updated balance.

    Runs only after explicit user confirmation (require_confirmation on the tool).
    """
    conn = get_connection()
    try:
        cur = conn.cursor()
        emp = _resolve_employee(cur, employee)
        if not emp:
            return {"status": "ERROR", "error": f"No employee matched '{employee}'."}
        leave_type = leave_type.upper()
        year = int(start_date[:4])

        calc = calculate_working_days(
            start_date, end_date, country_code=emp["country_code"]
        )
        if "error" in calc:
            return {"status": "ERROR", "error": calc["error"]}
        working_days = calc["working_days"]

        bal = cur.execute(
            "SELECT * FROM leave_balances WHERE employee_id=? AND leave_type=? "
            "AND year=?",
            (emp["employee_id"], leave_type, year),
        ).fetchone()
        if not bal:
            return {"status": "ERROR",
                    "error": f"No {leave_type} balance for {year}."}
        if working_days > bal["available_days"]:
            return {
                "status": "INSUFFICIENT_BALANCE",
                "working_days": working_days,
                "available_days": bal["available_days"],
                "error": f"Needs {working_days} days, only "
                         f"{bal['available_days']} available.",
            }

        request_id = _next_request_id(cur, year)
        cur.execute(
            "INSERT INTO leave_requests (request_id, employee_id, leave_type, "
            "start_date, end_date, working_days, status, submitted_at, notes) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (request_id, emp["employee_id"], leave_type, start_date, end_date,
             working_days, "APPROVED", now_iso(), notes or None),
        )
        new_used = bal["used_days"] + working_days
        new_avail = bal["total_days"] - new_used
        cur.execute(
            "UPDATE leave_balances SET used_days=?, available_days=? "
            "WHERE balance_id=?",
            (new_used, new_avail, bal["balance_id"]),
        )
        conn.commit()
        return {
            "status": "APPROVED",
            "request_id": request_id,
            "employee_id": emp["employee_id"],
            "full_name": emp["full_name"],
            "leave_type": leave_type,
            "start_date": start_date,
            "end_date": end_date,
            "working_days": working_days,
            "remaining_balance": new_avail,
        }
    finally:
        conn.close()
