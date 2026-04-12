"""Shared authentication decorators for Flask routes and Blueprints."""
import logging
from functools import wraps
from typing import Callable

from flask import jsonify, request

log = logging.getLogger(__name__)


def _require_localhost(f: Callable) -> Callable:
  """Restrict a route to localhost-only access.

  Returns HTTP 403 for any request not originating from 127.0.0.1 or ::1.
  Applied to all /api/pinnacle/* routes and existing /admin routes.
  """
  @wraps(f)
  def decorated(*args, **kwargs):
    if request.remote_addr not in ("127.0.0.1", "::1"):
      return jsonify({"error": "Admin access is restricted to localhost"}), 403
    return f(*args, **kwargs)
  return decorated
