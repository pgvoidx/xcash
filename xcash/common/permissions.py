from rest_framework.permissions import BasePermission
from rest_framework.request import Request


class RejectAll(BasePermission):
    # 明确拒绝所有请求，用于只开放特定 action 的 ViewSet 兜底权限。
    def has_permission(self, request: Request, view):
        return False

    def has_object_permission(self, request, view, obj):
        return False
