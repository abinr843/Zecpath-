from rest_framework.permissions import BasePermission


class IsAdminRole(BasePermission):
    """
    Allows access only to users with role == 'ADMIN'.
    Uses the app-level role field on CustomUser, not Django's is_staff.
    """

    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and getattr(request.user, 'role', None) == 'ADMIN'
        )
