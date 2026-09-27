from rest_framework.permissions import BasePermission


def business_id_for(user):
    profile = getattr(user, "account_profile", None)
    return profile.business_id if profile else None


def can_manage(user):
    if not user or not user.is_authenticated or not user.is_active:
        return False
    profile = getattr(user, "account_profile", None)
    if profile:
        return profile.role == "employer" and profile.business_id is not None
    return user.is_staff or user.is_superuser or user.groups.filter(name="Managers").exists()


def is_admin(user):
    if not user or not user.is_authenticated or not user.is_active:
        return False
    profile = getattr(user, "account_profile", None)
    return bool(profile and profile.role == "admin")


class IsManager(BasePermission):
    message = "Employer or manager access is required."

    def has_permission(self, request, view):
        return can_manage(request.user)


class IsAdmin(BasePermission):
    message = "Administrator access is required."

    def has_permission(self, request, view):
        return is_admin(request.user)
