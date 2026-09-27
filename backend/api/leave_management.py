from datetime import timedelta
from decimal import Decimal

from .models import Holiday, LeaveBalance, LeaveRequest


LEAVE_TYPES = ("annual", "sick", "maternity", "unpaid")
DEFAULT_ALLOCATIONS = {
    "annual": Decimal("20.0"),
    "sick": Decimal("10.0"),
    "maternity": Decimal("90.0"),
    "unpaid": Decimal("0.0"),
}


def leave_days(employee, start, end):
    """Count Monday-Friday leave days, excluding company holidays."""
    holidays = set(Holiday.objects.filter(
        business_id=employee.business_id, date__range=(start, end)).values_list("date", flat=True))
    current = start
    days = 0
    while current <= end:
        if current.weekday() < 5 and current not in holidays:
            days += 1
        current += timedelta(days=1)
    return Decimal(days)


def ensure_leave_balances(employee, year):
    balances = []
    for leave_type in LEAVE_TYPES:
        balance, _ = LeaveBalance.objects.get_or_create(
            employee=employee, leave_type=leave_type, year=year,
            defaults={"days_allocated": DEFAULT_ALLOCATIONS[leave_type]},
        )
        balances.append(balance)
    return balances


def used_days(employee, leave_type, year, exclude=None):
    requests = LeaveRequest.objects.filter(
        employee=employee, leave_type=leave_type, status="approved", start_date__year=year,
    )
    if exclude:
        requests = requests.exclude(pk=exclude)
    return sum((leave_days(employee, item.start_date, item.end_date) for item in requests), Decimal("0"))


def balance_summary(balance):
    used = used_days(balance.employee, balance.leave_type, balance.year)
    unlimited = balance.leave_type == "unpaid"
    return {
        "used_days": used,
        "remaining_days": None if unlimited else max(Decimal("0"), balance.days_allocated - used),
        "unlimited": unlimited,
    }
