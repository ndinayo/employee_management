"""Direct conversation between the platform administrator and a company.

One thread per company, in both directions. The sender picks the channel, and
it is always one or the other: a dashboard message appears in the other side's
thread and sends no email, while an email goes to their inbox and never shows in
their dashboard. Employees are not reachable through here: their correspondence
stays with their own employer.
"""
from django.contrib.auth import get_user_model
from django.db.models import Max, Q
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import (OpenApiExample, OpenApiParameter, extend_schema,
                                   extend_schema_view)
from rest_framework import serializers
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from . import onboarding
from .models import AccountProfile, Business, PlatformMessage
from .permissions import IsAdmin, IsManager, business_id_for
from .schema import RESPONSE_403_ADMIN, with_errors

BUSINESS_ID = OpenApiParameter(
    name="pk", type=OpenApiTypes.INT, location=OpenApiParameter.PATH, required=True,
    description="The company's numeric id.",
)


def admin_errors(success, **kwargs):
    return with_errors(success, forbidden=RESPONSE_403_ADMIN, **kwargs)


# --- Payload shapes ----------------------------------------------------------

class MessageBodySerializer(serializers.Serializer):
    body = serializers.CharField(max_length=5000)
    channel = serializers.ChoiceField(
        choices=["message", "email"], default="message",
        help_text="`message` keeps it inside the dashboard and sends no email. `email` sends "
                  "it to the recipient's inbox only, and it never appears in their thread. "
                  "One or the other, never both.")

    def validate_body(self, value):
        text = value.strip()
        if not text:
            raise serializers.ValidationError("Write a message before sending it.")
        return text


class PlatformMessageSerializer(serializers.Serializer):
    """One message in a company's thread."""

    id = serializers.IntegerField()
    from_admin = serializers.BooleanField(help_text="True when the platform administrator wrote it.")
    author = serializers.CharField(
        allow_blank=True, help_text="The sender's display name, or empty if that account is gone.")
    body = serializers.CharField()
    channel = serializers.ChoiceField(
        choices=["message", "email"],
        help_text="How it was sent. An emailed one is visible to its sender only.")
    created_at = serializers.CharField(help_text="Local-time ISO 8601 timestamp.")
    read = serializers.BooleanField(
        help_text="For a dashboard message, true once the other side has opened the thread.")
    emailed = serializers.BooleanField(
        help_text="For an emailed one, whether it actually reached the recipient's inbox.")


class ThreadSerializer(serializers.Serializer):
    """A company's whole conversation with the platform administrator."""

    business = serializers.IntegerField()
    business_name = serializers.CharField()
    unread = serializers.IntegerField(help_text="Messages from the other side you have not opened.")
    messages = PlatformMessageSerializer(many=True)


class ClearedSerializer(serializers.Serializer):
    """What a clear-everything call actually did."""

    cleared = serializers.IntegerField(help_text="How many messages were marked as read.")
    unread = serializers.IntegerField(help_text="What remains unread afterwards. Always 0.")


class ThreadSummarySerializer(serializers.Serializer):
    """One company's conversation, as listed for the administrator."""

    business = serializers.IntegerField()
    business_name = serializers.CharField()
    employer_username = serializers.CharField(allow_blank=True)
    employer_email = serializers.CharField(allow_blank=True)
    unread = serializers.IntegerField()
    last_body = serializers.CharField(allow_blank=True)
    last_at = serializers.CharField(allow_blank=True)
    last_from_admin = serializers.BooleanField()


# --- Shared helpers ----------------------------------------------------------

def as_when(value):
    if not value:
        return ""
    if timezone.is_aware(value):
        value = timezone.localtime(value)
    return value.isoformat()


def author_name(message):
    user = message.sender
    if not user:
        return "Platform team" if message.from_admin else ""
    return user.get_full_name().strip() or user.username


def as_message(message):
    return {
        "id": message.pk, "from_admin": message.from_admin, "author": author_name(message),
        "body": message.body, "channel": message.channel,
        "created_at": as_when(message.created_at),
        "read": message.channel == "message" and message.read_at is not None,
        # An emailed one is never opened in a dashboard, so read_at records the
        # moment it was handed to the mail server instead.
        "emailed": message.channel == "email" and message.read_at is not None,
    }


def visible_to(business, viewer_is_admin):
    """What this viewer may see of a company's thread.

    Dashboard messages are shared. An emailed one went to the other side's
    inbox and never to their dashboard, so only its sender keeps it on screen.
    """
    return PlatformMessage.objects.filter(business=business).filter(
        Q(channel="message") | Q(from_admin=viewer_is_admin)).select_related("sender")


def thread_for(business, viewer_is_admin):
    """The conversation, plus a count of what this viewer has not opened."""
    messages = list(visible_to(business, viewer_is_admin))
    unread = sum(1 for row in messages
                 if row.channel == "message" and row.read_at is None
                 and row.from_admin != viewer_is_admin)
    return {
        "business": business.pk, "business_name": business.name,
        "unread": unread, "messages": [as_message(row) for row in messages],
    }


def mark_read(business, viewer_is_admin):
    """Clear this viewer's unread badge for the company.

    Only dashboard messages carry a badge; an emailed one was never delivered
    here to be read.
    """
    return PlatformMessage.objects.filter(
        business=business, channel="message", from_admin=not viewer_is_admin,
        read_at__isnull=True,
    ).update(read_at=timezone.now())


def admin_emails():
    return [user.email for user in get_user_model().objects.filter(
        account_profile__role="admin", is_active=True) if user.email]


def employer_emails(business):
    return [profile.user.email for profile in AccountProfile.objects.filter(
        role="employer", business=business).select_related("user")
        if profile.user.email and profile.user.is_active]


def post_message(business, sender, from_admin, data):
    """Send on the channel the sender picked, and never on both.

    A dashboard message is stored and nothing is emailed. An emailed one is
    stored for the sender's own record, goes to the recipient's inbox, and
    stays out of their thread.
    """
    serializer = MessageBodySerializer(data=data)
    serializer.is_valid(raise_exception=True)
    channel = serializer.validated_data["channel"]
    message = PlatformMessage.objects.create(
        business=business, sender=sender, from_admin=from_admin,
        channel=channel, body=serializer.validated_data["body"])
    if channel != "email":
        return as_message(message)
    recipients = employer_emails(business) if from_admin else admin_emails()
    if onboarding.send_platform_message(message, recipients):
        message.read_at = timezone.now()
        message.save(update_fields=["read_at"])
    return as_message(message)


def unread_for_admin():
    """Dashboard messages from companies the administrator has not opened."""
    return PlatformMessage.objects.filter(
        channel="message", from_admin=False, read_at__isnull=True).count()


def unread_for_business(business_id):
    if not business_id:
        return 0
    return PlatformMessage.objects.filter(
        business_id=business_id, channel="message", from_admin=True,
        read_at__isnull=True).count()


# --- Administrator side ------------------------------------------------------

@extend_schema(
    tags=["Platform administration"],
    summary="List company conversations",
    description="Every company with the state of its conversation: the last message the "
                "administrator can see, and how many of that company's dashboard messages "
                "are still unopened. "
                "Companies nobody has written to are listed too, so a conversation can be "
                "started with any of them. Companies waiting on a reply come first.",
    responses=admin_errors({200: ThreadSummarySerializer(many=True)}, bad_request=False),
)
class AdminMessageListView(APIView):
    permission_classes = [IsAdmin]

    def get(self, request):
        businesses = list(Business.objects.select_related("owner_profile__user").order_by("name"))
        seen = PlatformMessage.objects.filter(Q(channel="message") | Q(from_admin=True))
        newest = seen.values("business").annotate(last=Max("id"))
        last_messages = {row.business_id: row for row in PlatformMessage.objects.filter(
            pk__in=[row["last"] for row in newest])}
        unread = {}
        for row in PlatformMessage.objects.filter(
                channel="message", from_admin=False, read_at__isnull=True,
        ).values_list("business_id", flat=True):
            unread[row] = unread.get(row, 0) + 1
        rows = []
        for business in businesses:
            profile = getattr(business, "owner_profile", None)
            last = last_messages.get(business.pk)
            rows.append({
                "business": business.pk, "business_name": business.name,
                "employer_username": profile.user.username if profile else "",
                "employer_email": profile.user.email if profile else "",
                "unread": unread.get(business.pk, 0),
                "last_body": last.body if last else "",
                "last_at": as_when(last.created_at) if last else "",
                "last_from_admin": bool(last and last.from_admin),
            })
        # Newest traffic first (companies never written to sort last on an empty
        # timestamp), then anything waiting on a reply is lifted to the top.
        rows.sort(key=lambda row: row["last_at"], reverse=True)
        rows.sort(key=lambda row: row["unread"] == 0)
        return Response(rows)


@extend_schema(tags=["Platform administration"], parameters=[BUSINESS_ID])
@extend_schema_view(
    get=extend_schema(
        operation_id="admin_messages_retrieve",
        summary="Read one company's conversation",
        description="Every message exchanged with this company, oldest first. Reading does "
                    "not clear the unread badge; POST to the `read/` endpoint for that.",
        responses=admin_errors({200: ThreadSerializer}, bad_request=False, not_found=True),
    ),
    post=extend_schema(
        operation_id="admin_messages_create",
        summary="Write to a company",
        description="Delivers on the channel named in `channel`, and only that one. A "
                    "`message` lands in the employer's dashboard and sends no email; an "
                    "`email` goes to their inbox and stays out of their dashboard. Either "
                    "way the sender keeps a copy in their own thread, so a mail failure "
                    "never loses what was written. `emailed` reports whether an emailed one "
                    "actually went out.",
        request=MessageBodySerializer,
        responses=admin_errors({201: PlatformMessageSerializer}, not_found=True),
        examples=[
            OpenApiExample("Dashboard message", request_only=True,
                           value={"body": "Your workspace is ready.", "channel": "message"}),
            OpenApiExample("Email instead", request_only=True,
                           value={"body": "Please confirm your billing address.",
                                  "channel": "email"}),
        ],
    ),
)
class AdminMessageThreadView(APIView):
    permission_classes = [IsAdmin]

    def get_business(self, pk):
        try:
            return Business.objects.get(pk=pk)
        except Business.DoesNotExist:
            raise NotFound("That company was not found.")

    def get(self, request, pk):
        return Response(thread_for(self.get_business(pk), viewer_is_admin=True))

    def post(self, request, pk):
        return Response(post_message(self.get_business(pk), request.user, True, request.data),
                        status=201)


@extend_schema(
    tags=["Platform administration"],
    parameters=[BUSINESS_ID],
    summary="Mark a company's messages as read",
    description="Clears the administrator's unread badge for this company and returns the "
                "thread as it now stands.",
    request=None,
    responses=admin_errors({200: ThreadSerializer}, bad_request=False, not_found=True),
)
class AdminMessageReadView(APIView):
    permission_classes = [IsAdmin]

    def post(self, request, pk):
        try:
            business = Business.objects.get(pk=pk)
        except Business.DoesNotExist:
            raise NotFound("That company was not found.")
        mark_read(business, viewer_is_admin=True)
        return Response(thread_for(business, viewer_is_admin=True))


@extend_schema(
    tags=["Platform administration"],
    summary="Mark every company's messages as read",
    description="Clears the whole messages badge in one call, for when there are more "
                "conversations than is practical to open one by one. The conversations "
                "themselves are untouched; only the unread marks are cleared. Returns how "
                "many messages were cleared.",
    request=None,
    responses=admin_errors({200: ClearedSerializer}, bad_request=False),
)
class AdminMessageReadAllView(APIView):
    permission_classes = [IsAdmin]

    def post(self, request):
        cleared = PlatformMessage.objects.filter(
            channel="message", from_admin=False, read_at__isnull=True,
        ).update(read_at=timezone.now())
        return Response({"cleared": cleared, "unread": unread_for_admin()})


# --- Company side ------------------------------------------------------------

def requesting_business(request):
    business_id = business_id_for(request.user)
    if not business_id:
        raise PermissionDenied("Only a company's employer can use this conversation.")
    return Business.objects.get(pk=business_id)


@extend_schema(tags=["Employer · Messages"])
@extend_schema_view(
    get=extend_schema(
        operation_id="messages_retrieve",
        summary="Read this company's conversation with the platform team",
        description="Every message exchanged with the administrator, oldest first. Reading "
                    "does not clear the unread badge; POST to the `read/` endpoint for that.",
        responses=with_errors({200: ThreadSerializer}, bad_request=False),
    ),
    post=extend_schema(
        operation_id="messages_create",
        summary="Write to the platform team",
        description="Delivers on the channel named in `channel`, and only that one. A "
                    "`message` lands in the administrator's dashboard and sends no email; an "
                    "`email` goes to their inbox and stays out of their dashboard.",
        request=MessageBodySerializer,
        responses=with_errors({201: PlatformMessageSerializer}),
        examples=[OpenApiExample(
            "Ask the platform team", request_only=True,
            value={"body": "Our invitation emails are not arriving.", "channel": "message"})],
    ),
)
class CompanyMessageView(APIView):
    permission_classes = [IsManager]

    def get(self, request):
        return Response(thread_for(requesting_business(request), viewer_is_admin=False))

    def post(self, request):
        business = requesting_business(request)
        return Response(post_message(business, request.user, False, request.data), status=201)


@extend_schema(
    tags=["Employer · Messages"],
    summary="Mark the platform team's messages as read",
    description="Clears this company's unread badge and returns the thread as it now stands.",
    request=None,
    responses=with_errors({200: ThreadSerializer}, bad_request=False),
)
class CompanyMessageReadView(APIView):
    permission_classes = [IsManager]

    def post(self, request):
        business = requesting_business(request)
        mark_read(business, viewer_is_admin=False)
        return Response(thread_for(business, viewer_is_admin=False))
