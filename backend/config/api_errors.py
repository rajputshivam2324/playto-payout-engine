"""
config/api_errors.py

Provides Stripe-style structured error responses for the API.

Key design decisions:
  - Every error body is shaped as {"error": {"code", "message", "param"}}.
  - DRF exceptions are normalized globally so authentication errors do not leak shapes.
"""

from rest_framework.response import Response
from rest_framework.views import exception_handler


def error_body(code, message, param=None):
    """
    Build a stable Stripe-style error payload.

    Args:
        code: Machine-readable error code.
        message: Human-readable explanation safe for clients.
        param: Optional request parameter responsible for the error.

    Returns:
        Dict matching the public API error contract.
    """
    return {"error": {"code": code, "message": message, "param": param}}


def error_response(code, message, param=None, status_code=400):
    """
    Return a DRF Response with the stable error shape.

    Args:
        code: Machine-readable error code.
        message: Human-readable explanation safe for clients.
        param: Optional request parameter responsible for the error.
        status_code: HTTP status to send.

    Returns:
        DRF Response containing the error body.
    """
    return Response(error_body(code=code, message=message, param=param), status=status_code)


def playto_exception_handler(exc, context):
    """
    Convert DRF-raised exceptions into Playto's stable error contract.

    Args:
        exc: Exception raised by DRF authentication, permissions, parsing, or validation.
        context: DRF exception context including the view.

    Returns:
        Response with {"error": {...}} or None for unhandled 500s.
    """
    response = exception_handler(exc, context)
    if response is None:
        # Returning None preserves Django's loud 500 behavior for truly unexpected bugs.
        return None

    detail = response.data.get("detail", response.data) if isinstance(response.data, dict) else response.data
    code = getattr(exc, "default_code", None) or getattr(detail, "code", None) or "api_error"
    message = str(detail)
    if isinstance(response.data, dict) and "detail" in response.data:
        # DRF ErrorDetail objects stringify cleanly and preserve a safe client message.
        message = str(response.data["detail"])

    response.data = error_body(code=str(code), message=message, param=None)
    return response
