"""
Centralized non-secret configuration for PaceIQ.

Migrated from data/odds.py. Secrets (credentials, tokens) belong in .env only.
Import constants from here: `from config import PINNACLE_API_BASE`
"""

import os

_ROOT: str = os.path.dirname(os.path.abspath(__file__))

# Pinnacle API
PINNACLE_API_BASE: str = "https://api.arcadia.pinnacle.com/0.1"
PINNACLE_HOME_URL: str = "https://www.pinnacle.ca/"
PINNACLE_CYCLING_SPORT_ID: int = 45
REQUEST_TIMEOUT: int = 60  # seconds

# File paths (resolved relative to project root)
KEY_CACHE_PATH: str = os.path.join(_ROOT, "data", ".pinnacle_key_cache")
ODDS_LOG_PATH: str = os.path.join(_ROOT, "data", "odds_log.jsonl")
SESSION_STATE_PATH: str = os.path.join(_ROOT, "data", ".pinnacle_session_state.json")
