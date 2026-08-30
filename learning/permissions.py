from rest_framework import permissions


class IsAdminOrReadOnly(permissions.BasePermission):
    # Anyone authenticated can GET (view topics/lessons/quizzes).
    # Only users with role="admin" can POST/PUT/PATCH/DELETE.
    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return request.user and request.user.is_authenticated
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.role == "admin"
        )
    
class IsOwnerOrAdminOrReadOnly(permissions.BasePermission):
    # Used specifically for Topic now that students can create their own:
    # - Anyone authenticated can view (queryset filtering handles WHICH
    #   topics they see — this permission only governs read vs write).
    # - Anyone authenticated can create a topic (they become its owner).
    # - Only the topic's owner or an admin can update/delete it — this
    #   stops student A from editing or deleting student B's topic.
    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return request.user and request.user.is_authenticated
        # Covers POST (create): any authenticated user may create a topic.
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return True
        return bool(
            request.user.role == "admin" or obj.owner_id == request.user.id
        )