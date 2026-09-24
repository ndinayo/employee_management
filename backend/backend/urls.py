from django.contrib import admin
from django.urls import include, path
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from .health import health
from api.accounts import AccountView, SignupView

urlpatterns = [
    path("api/health/", health, name="health"),
    path("api/signup/", SignupView.as_view(), name="signup"),
    path("api/account/", AccountView.as_view(), name="account"),
    path("admin/", admin.site.urls),
    path("api/token/", TokenObtainPairView.as_view(), name="get_token"),
    path("api/token/refresh/", TokenRefreshView.as_view(), name="refresh"),
    path("api-auth/", include("rest_framework.urls")),
    path("api/", include("api.urls")),
]
