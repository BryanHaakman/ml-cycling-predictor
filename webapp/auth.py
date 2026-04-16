"""Shared authentication decorators for Flask routes and Blueprints."""
import os
import logging
from functools import wraps
from typing import Callable

from flask import jsonify, redirect, request, session, url_for

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


def get_passcode() -> str | None:
  """Return the PASSCODE env var, or None if not set (no gate)."""
  return os.environ.get("PASSCODE")


def init_passcode_gate(app) -> None:
  """Register a before_request hook that gates all routes behind a passcode.

  If the PASSCODE env var is not set the gate is disabled entirely,
  allowing normal local development without any login screen.
  """
  @app.before_request
  def _check_passcode():
    # No passcode configured → no gate
    if not get_passcode():
      return None

    # Allow the login/logout routes and static files through
    if request.endpoint in ("login", "logout", "static"):
      return None

    # Already authenticated
    if session.get("authenticated"):
      return None

    # API requests get a 401 instead of a redirect
    if request.path.startswith("/api/"):
      return jsonify({"error": "Authentication required"}), 401

    return redirect(url_for("login"))
