from rest_framework.permissions import BasePermission
from rest_framework.request import Request


class RejectAll(BasePermission):
    # 明确拒绝所有请求，用于只开放特定 action 的 ViewSet 兜底权限。
    def has_permission(self, request: Request, view):
        return False

    def has_object_permission(self, request, view, obj):
        return False


class IsSuperUser(BasePermission):
    # 后台系统级操作只允许超级管理员访问，避免普通商户误入治理入口。
    def has_permission(self, request: Request, view):
        return request.user.is_superuser

    def has_object_permission(self, request, view, obj):
        return request.user.is_superuser
