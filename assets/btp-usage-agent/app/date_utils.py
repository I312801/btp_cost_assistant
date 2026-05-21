"""
Natural-language date parsing utilities.

Converts phrases like "this week", "last month", "yesterday", etc.
into the YYYYMMDD / YYYYMM formats expected by the BTP UAS API.
"""
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta


def today() -> date:
    return date.today()


def fmt(d: date) -> str:
    """Format a date as YYYYMMDD."""
    return d.strftime("%Y%m%d")


def fmt_month(d: date) -> str:
    """Format a date as YYYYMM."""
    return d.strftime("%Y%m")


def resolve_date_range(expression: str) -> tuple[str, str]:
    """
    Attempt to resolve a common English date expression into (fromDate, toDate)
    in YYYYMMDD format.

    Recognised patterns (case-insensitive):
      today, yesterday, this week, last week, this month, last month,
      this year, last year, last N days, last N weeks, last N months

    Falls back to (None, None) for unknown expressions so the LLM can pass
    explicit date strings instead.
    """
    expr = expression.strip().lower()
    t = today()

    if expr in ("today",):
        return fmt(t), fmt(t)

    if expr in ("yesterday",):
        d = t - timedelta(days=1)
        return fmt(d), fmt(d)

    if expr in ("this week", "current week"):
        monday = t - timedelta(days=t.weekday())
        return fmt(monday), fmt(t)

    if expr in ("last week", "previous week"):
        last_monday = t - timedelta(days=t.weekday() + 7)
        last_sunday = last_monday + timedelta(days=6)
        return fmt(last_monday), fmt(last_sunday)

    if expr in ("this month", "current month"):
        start = t.replace(day=1)
        return fmt(start), fmt(t)

    if expr in ("last month", "previous month"):
        first_of_this = t.replace(day=1)
        last_month_end = first_of_this - timedelta(days=1)
        last_month_start = last_month_end.replace(day=1)
        return fmt(last_month_start), fmt(last_month_end)

    if expr in ("this year", "current year"):
        start = t.replace(month=1, day=1)
        return fmt(start), fmt(t)

    if expr in ("last year", "previous year"):
        start = t.replace(year=t.year - 1, month=1, day=1)
        end = t.replace(year=t.year - 1, month=12, day=31)
        return fmt(start), fmt(end)

    import re
    m = re.match(r"last\s+(\d+)\s+(day|week|month)s?", expr)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        if unit == "day":
            start = t - timedelta(days=n)
        elif unit == "week":
            start = t - timedelta(weeks=n)
        else:
            start = t - relativedelta(months=n)
        return fmt(start), fmt(t)

    return None, None  # type: ignore[return-value]


def resolve_year_month(expression: str) -> str | None:
    """
    Resolve an expression like "this month", "last month", "May 2026", "2026-05"
    into YYYYMM format.
    """
    expr = expression.strip().lower()
    t = today()

    if expr in ("this month", "current month"):
        return fmt_month(t)

    if expr in ("last month", "previous month"):
        prev = t - relativedelta(months=1)
        return fmt_month(prev)

    import re
    month_names = {
        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
        "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    }

    m = re.match(r"(\d{4})[/-]?(\d{2})$", expr)
    if m:
        return m.group(1) + m.group(2)

    for name, num in month_names.items():
        if name in expr:
            year_m = re.search(r"\d{4}", expr)
            if year_m:
                return f"{year_m.group()}{num:02d}"

    return None
