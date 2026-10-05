from django.db import DatabaseError, connection
from django.http import JsonResponse
from django.views.decorators.http import require_GET


@require_GET
def health(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except DatabaseError:
        return JsonResponse({"status": "unavailable"}, status=503)
    from api import onboarding

    # Booleans and a provider name only: never the key or the sender address.
    provider = onboarding.delivery_provider()
    return JsonResponse({"status": "ok", "email": {
        "provider": provider,
        "brevo_configured": provider == "brevo",
    }})
