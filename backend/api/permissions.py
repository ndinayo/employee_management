from rest_framework.permissions import BasePermission


class IsManager(BasePermission):
    message = "Manager access is required."

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.is_active and (
            user.is_staff or user.is_superuser or user.groups.filter(name="Managers").exists()
        ))
