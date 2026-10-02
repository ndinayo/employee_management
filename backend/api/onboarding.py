"""Employee account provisioning.

An employer only enters a name, job title and email. The system creates the
sign-in account, emails a temporary password, and lets the employee complete
their own personal details once they sign in.
"""
import logging
import secrets
import string

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import get_connection, send_mail
from django.db import transaction
from django.db.models import Q

logger = logging.getLogger(__name__)

# Ambiguous characters are left out so the password survives being read off a
# phone screen and typed by hand.
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"


def generate_password(groups=3, size=4):
    return "-".join("".join(secrets.choice(ALPHABET) for _ in range(size)) for _ in range(groups))


def available_username(email):
    """Derive a username from the email local part, adding digits on collision."""
    base = "".join(ch for ch in email.split("@")[0].lower() if ch in string.ascii_lowercase + string.digits + "._-")
    base = (base or "employee")[:140]
    User = get_user_model()
    if not User.objects.filter(username__iexact=base).exists():
        return base
    while True:
        candidate = f"{base}{secrets.randbelow(9000) + 1000}"
        if not User.objects.filter(username__iexact=candidate).exists():
            return candidate


def email_is_taken(email, exclude_pk=None):
    return get_user_model().objects.filter(email__iexact=email).exclude(pk=exclude_pk).exists()


def reclaim_email(email, employee=None):
    """Remove leftover employee sign-ins so this email can be hired again.

    Returns False when a live employer, staff, or another employee's account
    still owns the address. Those must not be overwritten.
    """
    from .models import AccountProfile

    removable_ids = []
    for user in get_user_model().objects.filter(email__iexact=email):
        if user.is_staff or user.is_superuser:
            return False
        profile = AccountProfile.objects.filter(user=user).first()
        if profile and profile.role in ("employer", "admin"):
            return False
        if profile and profile.employee_id and (employee is None or profile.employee_id != employee.pk):
            return False
        removable_ids.append(user.pk)
    if removable_ids:
        get_user_model().objects.filter(pk__in=removable_ids).delete()
    return True


@transaction.atomic
def purge_employee(employee):
    """Delete the employee, their records, and every sign-in created for them.

    Related rows use PROTECT so a plain delete stops halfway and leaves the
    Django user behind. That leftover is what blocks hiring the same email.
    Employer accounts are never removed, even if they share the address.
    """
    from .models import AccountProfile, Attendance, Contract, LeaveRequest, Payroll, Salary

    email = employee.email
    leftover_users = AccountProfile.objects.filter(role="employee").filter(
        Q(employee=employee) | Q(employee__isnull=True, user__email__iexact=email)
    ).values_list("user_id", flat=True)
    user_ids = list(leftover_users)

    Contract.objects.filter(employee=employee).delete()
    Attendance.objects.filter(employee=employee).delete()
    LeaveRequest.objects.filter(employee=employee).delete()
    Payroll.objects.filter(employee=employee).delete()
    Salary.objects.filter(employee=employee).delete()
    employee.delete()
    get_user_model().objects.filter(pk__in=user_ids).delete()


@transaction.atomic
def provision_account(employee):
    """Create the sign-in account for a newly hired employee.

    Returns (user, raw_password). The caller is responsible for emailing it;
    the raw password is never stored.
    """
    from .models import AccountProfile

    User = get_user_model()
    password = generate_password()
    user = User.objects.create_user(
        username=available_username(employee.email),
        email=employee.email,
        password=password,
        first_name=employee.first_name,
        last_name=employee.last_name,
    )
    AccountProfile.objects.create(user=user, role="employee", employee=employee, must_change_password=True)
    return user, password


def sign_in_url():
    return f"{settings.FRONTEND_URL}/signin" if settings.FRONTEND_URL else "your employer's Employee Management site"


def shared_smtp():
    """Return the one database SMTP configuration shared by all employers.

    The Business fallback keeps credentials saved before the shared-settings
    migration usable during rolling deployments and in older test fixtures.
    """
    from .models import Business, InvitationEmailSettings

    configured = InvitationEmailSettings.objects.filter(pk=1).first()
    if configured:
        return configured if configured.email_host_user and configured.email_host_password else None
    return (Business.objects.exclude(email_host_user="").exclude(email_host_password="")
            .order_by("id").first())


def business_smtp(business=None):
    # Kept as the public helper used by account/platform serializers. SMTP is
    # now platform-wide, so the requesting business does not affect the result.
    return bool(shared_smtp())


def sender_owner_id():
    sender = shared_smtp()
    if not sender:
        return None
    if hasattr(sender, "owner_business_id"):
        return sender.owner_business_id
    return sender.pk


def can_manage_sender(business):
    owner_id = sender_owner_id()
    return bool(business and (owner_id is None or owner_id == business.pk))


def can_deliver(business=None):
    """True only when a real inbox can be reached, or tests pin EMAIL_DELIVERS."""
    return business_smtp() or bool(getattr(settings, "EMAIL_DELIVERS", False))


def from_address(business=None):
    sender = shared_smtp()
    if sender:
        return sender.email_host_user
    return settings.DEFAULT_FROM_EMAIL


def mail_connection(business=None, sender=None):
    """SMTP for this business, or the server default when that is configured.

    Django tests replace EMAIL_BACKEND with the in-memory backend; keep using
    that so mail.outbox still works while the business credentials are set.
    """
    backend = settings.EMAIL_BACKEND
    testing = backend.endswith("locmem.EmailBackend") or "inmemory" in backend
    sender = sender or shared_smtp()
    if sender and not testing:
        return get_connection(
            backend="django.core.mail.backends.smtp.EmailBackend",
            host=sender.email_host or "smtp.gmail.com",
            port=sender.email_port or 587,
            username=sender.email_host_user,
            password=sender.email_host_password,
            use_tls=sender.email_use_tls,
            timeout=getattr(settings, "EMAIL_TIMEOUT", 20),
            fail_silently=False,
        )
    if sender or can_deliver():
        return get_connection()
    return None


def send_invite(employee, user, password):
    """Email the temporary password. Returns True when the message was sent.

    Delivery failures must not undo the hire, so the caller keeps the employee
    record either way and shows the credentials to the employer instead.
    """
    connection = mail_connection(employee.business)
    if connection is None:
        return False
    business = employee.business.name if employee.business_id else "your employer"
    subject = f"Your {business} employee workspace is ready"
    body = (
        f"Hello {employee.first_name},\n\n"
        f"{business} has added you to Employee Management. An account has been created for you, "
        f"so there is nothing to sign up for.\n\n"
        f"Sign in here: {sign_in_url()}\n"
        f"Username: {user.username}\n"
        f"Email: {employee.email}\n"
        f"Temporary password: {password}\n\n"
        f"You can sign in with either your username or your email address. You will be asked to "
        f"choose your own password the first time you sign in.\n\n"
        f"Once you are in, please complete your profile: phone number, address and emergency "
        f"contact, so your employer has your details on file.\n\n"
        f"If you were not expecting this email, you can ignore it.\n"
    )
    try:
        sent = send_mail(subject, body, from_address(employee.business), [employee.email],
                         fail_silently=False, connection=connection)
        return bool(sent)
    except Exception:
        logger.exception("Invitation email to %s failed", employee.email)
        return False


def send_test(business, to, sender=None):
    """Prove the saved SMTP account can deliver before trusting it for hires."""
    connection = mail_connection(business, sender=sender)
    if connection is None:
        return False
    try:
        sent = send_mail(
            "Employee Management can send invitations",
            "This is a test message. If you received it, new employees will get their sign-in details by email.",
            sender.email_host_user if sender else from_address(business),
            [to], fail_silently=False, connection=connection,
        )
        return bool(sent)
    except Exception:
        logger.exception("Test invitation email to %s failed", to)
        return False


def send_contract_notification(contract, message=""):
    """Notify an employee that a digital contract is waiting for signature."""
    connection = mail_connection(contract.employee.business)
    if connection is None:
        return False
    business = contract.employee.business.name if contract.employee.business_id else "Your employer"
    destination = (f"{settings.FRONTEND_URL}/MyAccount/contract?contract={contract.pk}"
                   if settings.FRONTEND_URL else sign_in_url())
    employer_note = f"\nMessage from {business}:\n{message.strip()}\n" if message.strip() else ""
    try:
        sent = send_mail(
            f"Contract from {business} awaiting your signature",
            (
                f"Hello {contract.employee.first_name},\n\n"
                f"{business} has sent you the contract \"{contract.title}\" for your review and signature.\n\n"
                f"{employer_note}\n"
                f"Open this contract in your employee dashboard: {destination}\n\n"
                "Please read the complete contract before signing it."
            ),
            from_address(contract.employee.business), [contract.employee.email],
            fail_silently=False, connection=connection,
        )
        return bool(sent)
    except Exception:
        logger.exception("Contract notification to %s failed", contract.employee.email)
        return False


def send_contract_worker_approval_notification(contract, event):
    """Notify the employer after signing and congratulate the employee after approval."""
    employee = contract.employee
    connection = mail_connection(employee.business)
    if connection is None:
        return False
    business = employee.business.name if employee.business_id else "Your employer"
    if event == "signed":
        from .models import AccountProfile
        recipients = list(AccountProfile.objects.filter(
            business=employee.business, role="employer", user__email__gt="",
        ).values_list("user__email", flat=True).distinct()) if employee.business_id else []
        subject = f"Approve {employee} to start working"
        destination = (f"{settings.FRONTEND_URL}/dashboard/contracts"
                       if settings.FRONTEND_URL else sign_in_url())
        body = (
            f"{employee} has signed the contract \"{contract.title}\".\n\n"
            "Review the signed contract and approve this person as a worker before their workspace is unlocked.\n\n"
            f"Review contracts: {destination}"
        )
    else:
        recipients = [employee.email] if employee.email else []
        subject = f"Congratulations! You are approved to start working at {business}"
        destination = (f"{settings.FRONTEND_URL}/MyAccount"
                       if settings.FRONTEND_URL else sign_in_url())
        body = (
            f"Hello {employee.first_name},\n\n"
            f"Congratulations! {business} approved your signed contract and you may now start working.\n\n"
            f"Your employee workspace is now available: {destination}"
        )
    if not recipients:
        return False
    try:
        sent = send_mail(
            subject, body, from_address(employee.business), recipients,
            fail_silently=False, connection=connection,
        )
        return bool(sent)
    except Exception:
        logger.exception("Contract worker approval notification failed for contract %s", contract.pk)
        return False
def send_contract_termination_notification(termination, event):
    """Notify the other party whenever a contract termination changes."""
    contract = termination.contract
    employee = contract.employee
    connection = mail_connection(employee.business)
    if connection is None:
        return False
    business = employee.business.name if employee.business_id else "Your employer"
    employee_destination = (f"{settings.FRONTEND_URL}/MyAccount/contract"
                            if settings.FRONTEND_URL else sign_in_url())
    employer_destination = (f"{settings.FRONTEND_URL}/dashboard/contracts"
                            if settings.FRONTEND_URL else sign_in_url())
    if event in {"employee_requested", "employee_acknowledged"}:
        from .models import AccountProfile
        recipients = list(AccountProfile.objects.filter(
            business=employee.business, role="employer", user__email__gt="",
        ).values_list("user__email", flat=True).distinct()) if employee.business_id else []
        if event == "employee_requested":
            subject = f"{employee} requested contract termination"
            action = "submitted a termination request for employer review"
        else:
            subject = f"{employee} acknowledged contract termination"
            action = "acknowledged the termination and the contract is now terminated by mutual agreement"
        destination = employer_destination
    else:
        recipients = [employee.email] if employee.email else []
        if event == "employer_initiated":
            subject = f"{business} initiated contract termination"
            action = "initiated termination and is waiting for your acknowledgement"
        elif event == "employer_approved":
            subject = "Your contract termination request was approved"
            action = "approved your request; the contract is now terminated by mutual agreement"
        else:
            subject = "Your contract termination request was rejected"
            action = "rejected your termination request"
        destination = employee_destination
    if not recipients:
        return False
    notes = f"\nResponse notes: {termination.response_notes}\n" if termination.response_notes else ""
    body = (
        f"Contract: {contract.title}\n"
        f"{business} / {employee}\n\n"
        f"The other party has {action}.\n"
        f"Proposed last working date: {termination.proposed_last_working_date}\n"
        f"Reason: {termination.reason}\n"
        f"{notes}\nOpen the contract record: {destination}"
    )
    try:
        sent = send_mail(
            subject, body, from_address(employee.business), recipients,
            fail_silently=False, connection=connection,
        )
        return bool(sent)
    except Exception:
        logger.exception("Contract termination notification failed for contract %s", contract.pk)
        return False


def send_leave_notification(leave, event):
    """Email the other party when a leave request changes."""
    connection = mail_connection(leave.employee.business)
    if connection is None:
        return False
    employee = leave.employee
    business = employee.business.name if employee.business_id else "your employer"
    period = f"{leave.start_date} to {leave.end_date}"
    leave_name = leave.get_leave_type_display()
    destination = f"{settings.FRONTEND_URL}/MyAccount/leave" if settings.FRONTEND_URL else sign_in_url()

    if event in {"approved", "rejected"}:
        recipients = [employee.email] if employee.email else []
        subject = f"Your {leave_name.lower()} leave request was {event}"
        notes = f"\nEmployer notes: {leave.decision_notes}\n" if leave.decision_notes else ""
        body = (
            f"Hello {employee.first_name},\n\n"
            f"Your {leave_name.lower()} leave request for {period} was {event} by {business}.\n"
            f"{notes}\nView the request in your employee workspace: {destination}"
        )
    else:
        from .models import AccountProfile
        recipients = list(AccountProfile.objects.filter(
            business=employee.business, role="employer", user__email__gt="",
        ).values_list("user__email", flat=True).distinct()) if employee.business_id else []
        action = {"created": "submitted", "updated": "updated", "cancelled": "cancelled"}[event]
        subject = f"{employee} {action} a leave request"
        reason = f"\nReason: {leave.reason}\n" if leave.reason else ""
        body = (
            f"{employee} has {action} a {leave_name.lower()} leave request for {period}.\n"
            f"{reason}\nOpen Employee Management to review leave requests."
        )

    if not recipients:
        return False
    try:
        sent = send_mail(subject, body, from_address(employee.business), recipients,
                         fail_silently=False, connection=connection)
        return bool(sent)
    except Exception:
        logger.exception("Leave %s notification failed for request %s", event, leave.pk)
        return False


def send_password_reset(user, reset_url):
    """Send a password reset without revealing SMTP failures to public callers."""
    connection = mail_connection()
    if connection is None or not user.email:
        return False
    try:
        sent = send_mail(
            "Reset your Employee Management password",
            (
                f"Hello {user.get_full_name().strip() or user.username},\n\n"
                "A password reset was requested for your Employee Management account.\n"
                f"Username: {user.username}\n\n"
                f"Choose a new password: {reset_url}\n\n"
                "This link expires in one hour and can be used only once. "
                "If you did not request this, you can ignore this email."
            ),
            from_address(), [user.email], fail_silently=False, connection=connection,
        )
        return bool(sent)
    except Exception:
        logger.exception("Password reset email to user %s failed", user.pk)
        return False


def send_platform_message(message, recipients):
    """Email a platform message to the other side of the conversation.

    Only used for messages the sender chose to send by email; a dashboard
    message is never emailed. Delivery is best effort, and the sender keeps
    their own copy either way, so nothing written is ever lost to a mail
    problem.
    """
    if not recipients:
        return False
    connection = mail_connection(message.business)
    if connection is None:
        return False
    company = message.business.name
    if message.from_admin:
        subject = "Message from the Employee Management team"
        opening = f"The platform team sent {company} a message:"
        destination = f"{settings.FRONTEND_URL}/dashboard/messages" if settings.FRONTEND_URL else sign_in_url()
    else:
        subject = f"Message from {company}"
        opening = f"{company} sent the platform team a message:"
        destination = f"{settings.FRONTEND_URL}/admin/messages/{message.business_id}" if settings.FRONTEND_URL else sign_in_url()
    body = (
        f"{opening}\n\n"
        f"{message.body}\n\n"
        f"Reply from your dashboard: {destination}\n\n"
        "You are receiving this because you are on this conversation in Employee Management.\n"
    )
    try:
        sent = send_mail(subject, body, from_address(message.business), recipients,
                         fail_silently=False, connection=connection)
        return bool(sent)
    except Exception:
        logger.exception("Platform message %s could not be emailed", message.pk)
        return False
