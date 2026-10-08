"""Automatic payroll deductions: salary advance installments and asset misuse
recoveries.

Everything here is additive to the existing payroll records: deductions are
applied to a draft payroll record or while a salary is marked paid, and the
result is snapshotted so issued payslips never change afterwards.
"""
from decimal import ROUND_HALF_UP, Decimal

from django.db import IntegrityError, transaction
from rest_framework import serializers

from .models import (AdvanceRepayment, AssetIncident, Payroll, PayrollCalculation, PayrollDeductionLine,
                     PayrollPolicy, SalaryAdvance)

CENT = Decimal("0.01")
ZERO = Decimal("0.00")
HUNDRED = Decimal("100")


def money(value):
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def percent_of(amount, rate):
    return money(Decimal(amount) * Decimal(rate) / HUNDRED)


def payroll_policy(business_id):
    """The business's advance settings, created with defaults on first use."""
    policy = PayrollPolicy.objects.filter(business_id=business_id).first()
    if policy:
        return policy
    try:
        with transaction.atomic():
            return PayrollPolicy.objects.create(business_id=business_id)
    except IntegrityError:
        return PayrollPolicy.objects.get(business_id=business_id)


def calculation_is_current(payroll):
    """True when the payroll still carries the deductions its calculation produced."""
    calculation = getattr(payroll, "calculation", None)
    return bool(calculation and payroll.gross_pay == calculation.gross_pay
                and payroll.deductions == calculation.total_deductions)


def advance_figures(advance, exclude_payroll=None):
    """Repaid, scheduled and outstanding amounts for one advance."""
    repaid = scheduled = ZERO
    for repayment in advance.repayments.all():
        if exclude_payroll is not None and repayment.payroll_id == exclude_payroll:
            continue
        if repayment.payroll_id is None:
            repaid += repayment.amount
        elif repayment.payroll.status != "paid":
            scheduled += repayment.amount
        elif calculation_is_current(repayment.payroll):
            repaid += repayment.amount
    # A recorded advance counts as given to the employee; disbursement details are optional.
    outstanding = max(advance.amount - repaid, ZERO)
    if outstanding == ZERO:
        status = "repaid"
    elif repaid > ZERO:
        status = "partially_repaid"
    else:
        status = "disbursed"
    available = max(outstanding - scheduled, ZERO)
    next_installment = min(advance.installment_amount, outstanding)
    return {"total_repaid": repaid, "scheduled_deductions": scheduled, "outstanding_balance": outstanding,
            "available_to_deduct": available, "next_installment": next_installment, "status": status}


def recoverable_amount(incident):
    """A recorded incident is recovered in full unless a specific recovery amount was agreed."""
    return incident.recovery_amount if incident.recovery_amount > ZERO else incident.estimated_loss


def asset_recovery_figures(incident, exclude_payroll=None):
    """Recovered, scheduled and outstanding payroll recovery for one incident."""
    recovered = scheduled = ZERO
    for line in incident.payroll_deductions.all():
        payroll = line.calculation.payroll
        if exclude_payroll is not None and payroll.pk == exclude_payroll:
            continue
        if payroll.status != "paid":
            scheduled += line.amount
        elif calculation_is_current(payroll):
            recovered += line.amount
    outstanding = max(recoverable_amount(incident) - recovered, ZERO)
    available = max(outstanding - scheduled, ZERO)
    return {"recovered_amount": recovered, "scheduled_recovery": scheduled, "outstanding_recovery": outstanding,
            "available_to_deduct": available}


def advance_deductions(payroll, limit, limit_percent, lock=False):
    """Installments due in this payroll, within the deduction limit and balances."""
    advances = SalaryAdvance.objects.filter(
        employee=payroll.employee, first_repayment_month__lte=payroll.period_end,
    ).prefetch_related("repayments__payroll__calculation").order_by("issue_date", "id")
    if lock:
        advances = advances.select_for_update()
    remaining = limit
    lines, warnings = [], []
    for advance in advances:
        figures = advance_figures(advance, exclude_payroll=payroll.pk)
        if figures["available_to_deduct"] <= ZERO:
            continue
        if advance.currency != payroll.currency:
            warnings.append(f"An advance in {advance.currency} was not deducted from this {payroll.currency} payroll.")
            continue
        due = min(advance.installment_amount, figures["available_to_deduct"])
        amount = min(due, remaining)
        if amount < due:
            warnings.append(f"The advance installment was reduced to {amount} to stay within the "
                            f"{limit_percent}% deduction limit.")
        if amount <= ZERO:
            continue
        remaining -= amount
        lines.append({"kind": "advance", "name": f"Salary advance repayment (issued {advance.issue_date})",
                      "amount": amount, "salary_advance": advance, "asset_incident": None})
    return lines, warnings


def asset_deductions(payroll, limit, limit_percent, lock=False):
    """Recoveries for recorded asset incidents, within what is left of the limit."""
    incidents = AssetIncident.objects.filter(
        employee=payroll.employee, incident_date__lte=payroll.period_end,
    ).prefetch_related("payroll_deductions__calculation__payroll__calculation").order_by("incident_date", "id")
    if lock:
        incidents = incidents.select_for_update()
    remaining = limit
    lines, warnings = [], []
    for incident in incidents:
        due = asset_recovery_figures(incident, exclude_payroll=payroll.pk)["available_to_deduct"]
        if due <= ZERO:
            continue
        if incident.currency != payroll.currency:
            warnings.append(f"An asset recovery in {incident.currency} was not deducted from this "
                            f"{payroll.currency} payroll.")
            continue
        amount = min(due, remaining)
        if amount < due:
            warnings.append(f"The {incident.asset_name} recovery was reduced to {amount} to stay within the "
                            f"{limit_percent}% deduction limit. The rest is deducted in later months.")
        if amount <= ZERO:
            continue
        remaining -= amount
        lines.append({"kind": "asset", "name": f"Asset misuse recovery: {incident.asset_name} ({incident.incident_date})",
                      "amount": amount, "salary_advance": None, "asset_incident": incident})
    return lines, warnings


def calculate_payroll(payroll, other_deductions, lock=False):
    policy = payroll_policy(payroll.employee.business_id)
    limit_percent = policy.advance_deduction_limit_percent
    gross = money(payroll.gross_pay)
    other_deductions = money(other_deductions)
    limit = percent_of(max(gross - other_deductions, ZERO), limit_percent)
    advance_lines, warnings = advance_deductions(payroll, limit, limit_percent, lock=lock)
    advance_total = sum((line["amount"] for line in advance_lines), ZERO)
    asset_lines, asset_warnings = asset_deductions(payroll, limit - advance_total, limit_percent, lock=lock)
    asset_total = sum((line["amount"] for line in asset_lines), ZERO)
    lines = advance_lines + asset_lines
    if other_deductions:
        lines.append({"kind": "other", "name": "Other deductions", "amount": other_deductions,
                      "salary_advance": None, "asset_incident": None})
    total = advance_total + asset_total + other_deductions
    return {"gross_pay": gross, "lines": lines, "advance_deductions": advance_total,
            "asset_deductions": asset_total, "other_deductions": other_deductions, "total_deductions": total,
            "net_pay": gross - total, "warnings": warnings + asset_warnings, "limit_percent": limit_percent}


def apply_payroll_calculation(payroll_id, *, other_deductions=None, calculated_by=""):
    """Recalculate and store automatic deductions for a draft payroll record.

    Running it again replaces the previous lines and scheduled advance and
    asset deductions for this payroll, so nothing is ever deducted twice.
    """
    with transaction.atomic():
        payroll = Payroll.objects.select_for_update(of=("self",)).select_related("employee").get(pk=payroll_id)
        if payroll.status != "draft":
            raise serializers.ValidationError("Deductions can only be calculated on draft payroll records.")
        existing = PayrollCalculation.objects.filter(payroll=payroll).first()
        if other_deductions is None:
            other_deductions = existing.other_deductions if existing else payroll.deductions
        if Decimal(other_deductions) < 0:
            raise serializers.ValidationError({"other_deductions": "Other deductions cannot be negative."})
        result = calculate_payroll(payroll, other_deductions, lock=True)
        if result["total_deductions"] > result["gross_pay"]:
            raise serializers.ValidationError("These deductions would exceed gross pay. Reduce other deductions first.")
        AdvanceRepayment.objects.filter(payroll=payroll).delete()
        fields = {key: result[key] for key in ("gross_pay", "advance_deductions", "asset_deductions",
                                               "other_deductions", "total_deductions", "net_pay", "warnings")}
        calculation, _ = PayrollCalculation.objects.update_or_create(
            payroll=payroll, defaults={**fields, "calculated_by": calculated_by})
        calculation.lines.all().delete()
        PayrollDeductionLine.objects.bulk_create([
            PayrollDeductionLine(calculation=calculation, position=index, **line)
            for index, line in enumerate(result["lines"])
        ])
        AdvanceRepayment.objects.bulk_create([
            AdvanceRepayment(advance=line["salary_advance"], payroll=payroll, amount=line["amount"],
                             repaid_on=payroll.period_end, source="payroll", recorded_by=calculated_by,
                             notes="Deducted through payroll.")
            for line in result["lines"] if line["kind"] == "advance"
        ])
        payroll.deductions = result["total_deductions"]
        payroll.save(update_fields=["deductions"])
    return payroll, calculation
