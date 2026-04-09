from typing import Any

from django.http import JsonResponse
from rest_framework.exceptions import APIException

from common.error_codes import ErrorCode


class APIError(APIException):
    """统一的业务异常，DRF 与 Django 视图共享。"""

    default_code = "api_error"

    def __init__(self, error_code: ErrorCode, detail: Any = ""):
        self.error_code = error_code
        payload = error_code.to_payload(detail)
        super().__init__(detail=payload)
        self.status_code = error_code.status

    def to_response(self) -> JsonResponse:
        return JsonResponse(self.detail, status=self.status_code)
