"""Pytest configuration and shared fixtures."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def pytest_configure(config):
  """Register custom pytest marks."""
  config.addinivalue_line(
    "markers",
    "integration: live integration tests that make real network calls (deselect with -m 'not integration')",
  )
