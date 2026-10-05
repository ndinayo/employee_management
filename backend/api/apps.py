import logging
import os

from django.apps import AppConfig
from django.conf import settings

logger = logging.getLogger("api")


class ApiConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'api'

    def ready(self):
        if getattr(settings, "RUNNING_TESTS", False):
            return
        # Shows in the Render deploy and runtime logs. Never logs the key itself.
        if settings.BREVO_API_KEY:
            logger.info("Email delivery: Brevo API key loaded; sending as %s.", settings.DEFAULT_FROM_EMAIL)
            return
        level = logging.WARNING if getattr(settings, "ON_RENDER", False) else logging.INFO
        logger.log(level, "Email delivery: BREVO_API_KEY is not set, so Brevo is off.")
        lookalikes = [name for name in os.environ if "BREVO" in name.upper() and name != "BREVO_API_KEY"]
        if lookalikes:
            logger.warning("Found similar environment variable names %s. The name must be exactly "
                           "BREVO_API_KEY.", ", ".join(repr(name) for name in lookalikes))
