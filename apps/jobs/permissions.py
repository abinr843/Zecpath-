from rest_framework.permissions import BasePermission


class IsEmployer(BasePermission):
    def has_permission(self,request,view):
        return bool(
            request.user and
            request.user.is_authenticated and
            request.user.role == 'EMPLOYER'
        )


class IsCandidate(BasePermission):
    def has_permission(self,request,view):
        return bool(
            request.user and
            request.user.is_authenticated and
            request.user.role =='CANDIDATE'
        )

class IsApplicationOwnerOrEmployer(BasePermission):
    """
    Object-level permission to only allow owners of an object to edit it.
    Assumes the model instance has an `employer` or `candidate` attribute.
    """
    def has_object_permission(self, request, view, obj):
        if request.user.role == 'ADMIN' or request.user.is_superuser:
            return True
        if request.user.role == 'CANDIDATE':
            return obj.candidate.user == request.user
        elif request.user.role == 'EMPLOYER':
            return obj.job.employer.user == request.user
        return False


class IsJobOwner(BasePermission):
    """
    Object-level permission: only the Employer who posted the job
    linked to this Application can perform this action.
    Used by the status_update endpoint so only the hiring employer
    can move candidates through the ATS pipeline.
    """
    def has_permission(self, request, view):
        return bool(
            request.user and
            request.user.is_authenticated and
            request.user.role == 'EMPLOYER'
        )

    def has_object_permission(self, request, view, obj):
        return obj.job.employer.user == request.user


class IsJobAuthor(BasePermission):
    """
    Object-level permission to only allow the employer who created a job to edit/delete it.
    """
    def has_object_permission(self, request, view, obj):
        if request.user.role == 'EMPLOYER':
            return obj.employer.user == request.user
        return False