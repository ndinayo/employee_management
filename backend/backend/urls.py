from django.contrib import admin
from django.urls import include, path
from rest_framework_simplejwt.views import TokenRefreshView
from .health import health
from api.accounts import (AccountView, EmailSettingsView, MyContractSignView, MyContractsView,
                          MyContractTerminationAcknowledgeView, MyContractTerminationView,
                          MyAnnouncementReadView, MyAnnouncementsView, MyAttendanceView,
                          MyAnnouncementReadAllView, MyCalendarEventReadView, MyCalendarReadAllView,
                          MyCalendarView, MyLeaveDetailView, MyLeaveView, MyPhotoView, MyProfileView,
                          PasswordChangeView, PasswordResetConfirmView,
                          PasswordResetRequestView, SignupView, TokenView)
from api.dashboard import AdminHealthView, AdminOverviewView
from api.messaging import (AdminMessageListView, AdminMessageReadAllView, AdminMessageReadView,
                           AdminMessageThreadView, CompanyMessageReadView, CompanyMessageView)
from api.platform import (AdminBusinessDetailView, AdminBusinessListView, AdminEmployeeDetailView,
                          AdminEmployeeListView, EmployerDetailView, EmployerListView)
from drf_spectacular.views import (SpectacularAPIView, SpectacularRedocView,
                                   SpectacularSwaggerView)

urlpatterns = [
    path("api/health/", health, name="health"),
    path("api/signup/", SignupView.as_view(), name="signup"),
    path("api/password-reset/", PasswordResetRequestView.as_view(), name="password-reset"),
    path("api/password-reset/confirm/", PasswordResetConfirmView.as_view(), name="password-reset-confirm"),
    path("api/admin/overview/", AdminOverviewView.as_view(), name="admin-overview"),
    path("api/admin/health/", AdminHealthView.as_view(), name="admin-health"),
    path("api/admin/businesses/", AdminBusinessListView.as_view(), name="admin-businesses"),
    path("api/admin/businesses/<int:pk>/", AdminBusinessDetailView.as_view(), name="admin-business"),
    path("api/admin/employers/", EmployerListView.as_view(), name="admin-employers"),
    path("api/admin/employers/<int:pk>/", EmployerDetailView.as_view(), name="admin-employer"),
    path("api/admin/employees/", AdminEmployeeListView.as_view(), name="admin-employees"),
    path("api/admin/employees/<int:pk>/", AdminEmployeeDetailView.as_view(), name="admin-employee"),
    path("api/admin/messages/", AdminMessageListView.as_view(), name="admin-messages"),
    path("api/admin/messages/read-all/", AdminMessageReadAllView.as_view(), name="admin-messages-read-all"),
    path("api/admin/messages/<int:pk>/", AdminMessageThreadView.as_view(), name="admin-message-thread"),
    path("api/admin/messages/<int:pk>/read/", AdminMessageReadView.as_view(), name="admin-message-read"),
    path("api/messages/", CompanyMessageView.as_view(), name="company-messages"),
    path("api/messages/read/", CompanyMessageReadView.as_view(), name="company-messages-read"),
    path("api/account/", AccountView.as_view(), name="account"),
    path("api/account/email/", EmailSettingsView.as_view(), name="account-email"),
    path("api/account/password/", PasswordChangeView.as_view(), name="password-change"),
    path("api/me/profile/", MyProfileView.as_view(), name="my-profile"),
    path("api/me/announcements/", MyAnnouncementsView.as_view(), name="my-announcements"),
    path("api/me/announcements/read-all/", MyAnnouncementReadAllView.as_view(), name="my-announcements-read-all"),
    path("api/me/announcements/<int:pk>/read/", MyAnnouncementReadView.as_view(), name="my-announcement-read"),
    path("api/me/calendar/", MyCalendarView.as_view(), name="my-calendar"),
    path("api/me/calendar/read-all/", MyCalendarReadAllView.as_view(), name="my-calendar-read-all"),
    path("api/me/calendar/<int:pk>/read/", MyCalendarEventReadView.as_view(), name="my-calendar-event-read"),
    path("api/me/photo/", MyPhotoView.as_view(), name="my-photo"),
    path("api/me/attendance/", MyAttendanceView.as_view(), name="my-attendance"),
    path("api/me/leave/", MyLeaveView.as_view(), name="my-leave"),
    path("api/me/leave/<int:pk>/", MyLeaveDetailView.as_view(), name="my-leave-detail"),
    path("api/me/contracts/", MyContractsView.as_view(), name="my-contracts"),
    path("api/me/contracts/<int:pk>/sign/", MyContractSignView.as_view(), name="my-contract-sign"),
    path("api/me/contracts/<int:pk>/termination/", MyContractTerminationView.as_view(), name="my-contract-termination"),
    path("api/me/contracts/<int:pk>/termination/acknowledge/", MyContractTerminationAcknowledgeView.as_view(), name="my-contract-termination-acknowledge"),
    path("admin/", admin.site.urls),
    path("api/token/", TokenView.as_view(), name="get_token"),
    path("api/token/refresh/", TokenRefreshView.as_view(), name="refresh"),
    path("api-auth/", include("rest_framework.urls")),
    # Interactive API documentation. The schema is generated from the views and
    # serializers below, so it stays in step with them automatically.
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
    path("api/", include("api.urls")),
]
