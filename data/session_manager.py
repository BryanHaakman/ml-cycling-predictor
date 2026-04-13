"""
Playwright-based Pinnacle session acquisition with adaptive TTL.

Automates login to pinnacle.ca via headless Chromium, extracts the X-Session
token from response headers or cookies, and caches it with an adaptive TTL
that learns from real session expiry events.

Auth acquisition order (called from data/odds.py._get_api_key):
  1. PINNACLE_SESSION_COOKIE env var override (checked in odds.py, not here)
  2. Disk cache + adaptive TTL check -> return cached token if fresh
  3. Playwright headless login -> extract token -> update cache + TTL
  4. JS bundle extraction fallback (handled in odds.py, not here)

Public interface:
  - get_session_token()                  -> str or None (cache -> Playwright -> None)
  - invalidate_session()                 -> None (update TTL, clear cached token)
  - acquire_session_token(headless=True) -> str (Playwright login)
  - acquire_session_token_with_fallback()-> str (headless first, headed on CAPTCHA)
  - CaptchaOrMfaDetected                 -> Exception subclass
"""

import json
import logging
import os
import time
from typing import Optional

from config import SESSION_STATE_PATH, PINNACLE_HOME_URL

log = logging.getLogger(__name__)

# Sentinel for "no TTL learned yet" — ~115 days, far longer than any real session
_TTL_INFINITY_SENTINEL: int = 9_999_999

# Default state returned when no state file exists or file is unreadable
_DEFAULT_STATE: dict = {
  "token": None,
  "last_acquired": 0.0,
  "learned_ttl_seconds": _TTL_INFINITY_SENTINEL,
}


class CaptchaOrMfaDetected(Exception):
  """Raised when CAPTCHA or MFA is detected during headless Playwright login.

  Triggers a retry with headless=False so the user can solve manually.
  """


def _load_session_state() -> dict:
  """Load session state from SESSION_STATE_PATH.

  Returns:
    Dict with keys: token (str or None), last_acquired (float),
    learned_ttl_seconds (int). Returns defaults on missing file or
    parse error — never raises.
  """
  defaults = dict(_DEFAULT_STATE)
  if not os.path.exists(SESSION_STATE_PATH):
    return defaults
  try:
    with open(SESSION_STATE_PATH, "r", encoding="utf-8") as f:
      loaded = json.load(f)
    # Merge loaded values over defaults (handles partial state files)
    return {**defaults, **loaded}
  except (OSError, json.JSONDecodeError) as e:
    log.warning("_load_session_state: could not read %s: %s — returning defaults", SESSION_STATE_PATH, e)
    return defaults


def _save_session_state(state: dict) -> None:
  """Persist session state to SESSION_STATE_PATH as JSON.

  Ensures learned_ttl_seconds is stored as an integer (never a float infinity).
  Silently logs and returns on write failure — does not raise.

  Args:
    state: Dict with keys: token, last_acquired, learned_ttl_seconds.
  """
  state_to_save = dict(state)
  # Ensure TTL is stored as int (guard against float infinity per A4 in RESEARCH.md)
  ttl = state_to_save.get("learned_ttl_seconds", _TTL_INFINITY_SENTINEL)
  if not isinstance(ttl, int) or ttl != ttl:  # nan/inf guard
    ttl = _TTL_INFINITY_SENTINEL
  state_to_save["learned_ttl_seconds"] = int(ttl)

  try:
    with open(SESSION_STATE_PATH, "w", encoding="utf-8") as f:
      json.dump(state_to_save, f)
  except OSError as e:
    log.warning("_save_session_state: could not write %s: %s", SESSION_STATE_PATH, e)


def _is_session_fresh(state: dict) -> bool:
  """Check whether the cached session token is still within its adaptive TTL.

  Returns True if:
    - state["token"] is truthy, AND
    - Either TTL is the infinity sentinel (never proactively expire), OR
      the session age is less than the learned TTL.

  Args:
    state: Session state dict from _load_session_state().

  Returns:
    True if session is fresh and can be reused. False otherwise.
  """
  token = state.get("token")
  if not token:
    return False

  ttl = state.get("learned_ttl_seconds", _TTL_INFINITY_SENTINEL)
  if ttl == _TTL_INFINITY_SENTINEL:
    # No TTL learned yet — always treat as fresh if token exists
    return True

  age = time.time() - state.get("last_acquired", 0.0)
  return age < ttl


def acquire_session_token(headless: bool = True) -> str:
  """Login to pinnacle.ca via Playwright and extract the X-Session token.

  Uses headless Chromium by default. Intercepts API response headers to
  capture the x-session token (lowercase — Playwright normalizes headers).
  Falls back to cookies if header interception misses the token.

  Playwright is imported inside this function to avoid import-time
  dependency when mocking in tests (per RESEARCH.md Pitfall 6).

  Credentials are read from os.environ at call time — never at module level
  (per RESEARCH.md Pitfall 6).

  Args:
    headless: If True (default), runs headless. Set False for CAPTCHA fallback.

  Returns:
    The X-Session token string extracted from the login flow.

  Raises:
    CaptchaOrMfaDetected: If post-login indicator not found within timeout —
      likely CAPTCHA or 2FA blocking headless login.
    PinnacleAuthError: If login appears to succeed but no token is found.
    KeyError: If PINNACLE_USERNAME or PINNACLE_PASSWORD env vars not set.
  """
  from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
  from data.odds import PinnacleAuthError

  captured_token: dict = {}

  def on_request(request) -> None:
    """Capture x-session from outgoing request headers to Pinnacle API."""
    if "arcadia.pinnacle.com" in request.url:
      session = request.headers.get("x-session")
      if session:
        captured_token["value"] = session

  with sync_playwright() as p:
    browser = p.chromium.launch(headless=headless)
    context = browser.new_context()
    page = context.new_page()
    page.on("request", on_request)

    # Navigate directly to cycling matchups (token captured from any page's login)
    page.goto(PINNACLE_HOME_URL + "en/cycling/matchups/")

    # Dismiss cookie consent banner if present
    try:
      page.get_by_role("button", name="ACCEPT").click(timeout=5000)
    except PlaywrightTimeoutError:
      pass  # No cookie banner — continue

    # Fill credentials in the header bar fields
    page.get_by_placeholder("Email or ClientID").first.fill(os.environ["PINNACLE_USERNAME"])
    page.get_by_placeholder("password").first.fill(os.environ["PINNACLE_PASSWORD"])

    # Click header "LOG IN" — opens login modal with pre-filled credentials
    page.get_by_role("button", name="Log In").first.click()

    # Check the "I am fit for play" checkbox in the modal
    try:
      # Try the checkbox input first (the square), then fall back to text label
      checkbox = page.get_by_role("checkbox", name="I am fit for play")
      if checkbox.count() > 0:
        checkbox.check(timeout=10000)
      else:
        # Fall back to clicking the label/text which may also toggle the checkbox
        page.get_by_text("I am fit for play").click(timeout=10000)
    except PlaywrightTimeoutError:
      browser.close()
      raise CaptchaOrMfaDetected(
        "'I am fit for play' checkbox not found — headless mode may not render the login modal"
      )

    # Click the modal's "Log In" submit button
    # Use the last "Log In" button (modal submit, not header)
    try:
      page.get_by_role("button", name="Log In").last.click()
    except PlaywrightTimeoutError:
      browser.close()
      raise CaptchaOrMfaDetected(
        "Modal 'Log In' button not found — headless mode may not render the login modal"
      )

    # Poll for x-session header in outgoing requests — login + GeoComply takes time
    max_wait_ms = 30000
    poll_interval_ms = 1000
    elapsed = 0
    while elapsed < max_wait_ms and not captured_token.get("value"):
      page.wait_for_timeout(poll_interval_ms)
      elapsed += poll_interval_ms

    if captured_token.get("value"):
      log.info(
        "acquire_session_token: x-session captured from outgoing request (after %ds)",
        elapsed // 1000,
      )

    browser.close()

  if not captured_token.get("value"):
    from data.odds import PinnacleAuthError
    raise PinnacleAuthError(
      "Playwright login completed but no x-session header was captured from API requests. "
      "The login may have failed silently or GeoComply verification timed out."
    )

  token = captured_token["value"]
  log.info("acquire_session_token: token acquired (headless=%s, first 10 chars: %s...)", headless, token[:10])
  return token


def acquire_session_token_with_fallback() -> str:
  """Attempt headless Playwright login, falling back to headed browser on CAPTCHA/MFA.

  Tries headless=True first. If CaptchaOrMfaDetected is raised (timeout on
  post-login element), re-launches with headless=False so the user can solve
  the challenge manually.

  Returns:
    The X-Session token string.

  Raises:
    Any exception from acquire_session_token(headless=False) if headed also fails.
  """
  try:
    return acquire_session_token(headless=True)
  except CaptchaOrMfaDetected:
    log.warning(
      "acquire_session_token_with_fallback: CAPTCHA or 2FA detected — "
      "re-launching with headed browser for manual solve"
    )
    return acquire_session_token(headless=False)


def get_session_token() -> Optional[str]:
  """Get a valid Pinnacle session token, using cache or Playwright as needed.

  Lookup order (D-09: check-on-trigger, not background):
    1. Load state from disk — if token is fresh within adaptive TTL, return it
    2. Call acquire_session_token_with_fallback() — headless Playwright login
    3. On success: update state (token + timestamp), persist to disk
    4. On failure: log error, return None (caller handles gracefully)

  Returns:
    The session token string, or None if acquisition failed.
  """
  state = _load_session_state()

  if _is_session_fresh(state):
    log.info("get_session_token: returning cached token (age within TTL)")
    return state["token"]

  log.info("get_session_token: cache stale or empty — launching Playwright")
  try:
    token = acquire_session_token_with_fallback()
    state["token"] = token
    state["last_acquired"] = time.time()
    # Preserve existing learned_ttl_seconds — do not reset it on fresh acquisition
    _save_session_state(state)
    return token
  except Exception as e:
    log.warning("get_session_token: Playwright acquisition failed: %s", e)
    return None


def invalidate_session() -> None:
  """Invalidate the cached session token and update the adaptive TTL.

  Called when a 401/403 is received during a fetch. Computes how long the
  session actually lasted and tightens the TTL if this is shorter than the
  currently learned value (TTL only shrinks, never grows — D-07).

  Updates state: clears token, updates learned_ttl_seconds, persists to disk.
  """
  state = _load_session_state()

  age = time.time() - state.get("last_acquired", 0.0)
  current_ttl = state.get("learned_ttl_seconds", _TTL_INFINITY_SENTINEL)

  if age > 0 and age < current_ttl:
    # Session expired before the current TTL estimate — tighten the TTL
    new_ttl = int(age)
    log.info(
      "invalidate_session: session expired after ~%ds (TTL was %s) — updating TTL to %d",
      int(age),
      current_ttl,
      new_ttl,
    )
    state["learned_ttl_seconds"] = new_ttl
  else:
    log.info(
      "invalidate_session: session age %ds >= TTL %s — TTL unchanged",
      int(age),
      current_ttl,
    )

  state["token"] = None
  _save_session_state(state)
