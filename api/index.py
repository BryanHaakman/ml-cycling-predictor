"""Vercel serverless entry point — exposes the Flask app as a WSGI handler."""

import os
import sys

# Ensure project root is on the path so absolute imports work.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from webapp.app import app  # noqa: E402  — Vercel discovers this automatically.
