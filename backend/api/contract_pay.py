"""Pay follows the employee's contract.

A pay period can be paid only while a contract the employee signed and the
employer approved covers it, and that contract's monthly salary is what is
paid. Contracts written before contracts carried a salary fall back to the
employee's Salary record.
"""
from django.db.models import Q
from rest_framework import serializers

from .models import Contract, Salary


def covering_contract(employee, period_start, period_end):
    """The newest signed and approved contract in force during the period."""
    return (Contract.objects
            .filter(employee=employee, signature_status="signed", worker_approval_status="approved",
                    start_date__lte=period_end)
            .filter(Q(end_date__isnull=True) | Q(end_date__gte=period_start))
            .exclude(status="draft")
            .order_by("-start_date", "-id").first())


def require_contract(employee, period_start, period_end, label=None):
    contract = covering_contract(employee, period_start, period_end)
    if contract is None:
        when = label or f"{period_start} to {period_end}"
        raise serializers.ValidationError({"detail": (
            f"{employee} has no signed and approved contract covering {when}. "
            "Pay is only recorded for periods a contract covers.")})
    return contract


def contract_pay(contract, employee):
    """(monthly amount, currency) agreed in the contract, or the legacy Salary record."""
    if contract.monthly_salary is not None:
        return contract.monthly_salary, contract.salary_currency
    salary = Salary.objects.filter(employee=employee).first()
    if salary is None:
        raise serializers.ValidationError({"detail": (
            f"{contract.title} does not state a salary and {employee} has no salary on record.")})
    return salary.monthly_amount, salary.currency


def current_contract_salary(employee):
    """The latest approved contract that states a salary, if any."""
    return (Contract.objects
            .filter(employee=employee, signature_status="signed", worker_approval_status="approved",
                    monthly_salary__isnull=False)
            .exclude(status="draft")
            .order_by("-start_date", "-id").first())


def sync_salary(contract):
    """Mirror an approved contract's salary onto the employee's Salary record."""
    if contract.monthly_salary is None:
        return
    Salary.objects.update_or_create(employee=contract.employee, defaults={
        "monthly_amount": contract.monthly_salary, "currency": contract.salary_currency,
        "effective_date": contract.start_date, "notes": f"From the contract “{contract.title}”.",
    })
