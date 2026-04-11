# Phase 1: Pinnacle API Discovery and Client - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-11
**Phase:** 01-pinnacle-api-discovery-and-client
**Areas discussed:** Discovery approach, OddsMarket schema, Odds format, Empty market behavior

---

## Discovery Approach

| Option | Description | Selected |
|--------|-------------|----------|
| User inspects manually | User uses DevTools Network tab, pastes endpoint + headers + example response | |
| Write a Playwright capture script | Python script using playwright navigates Pinnacle and captures the request | |
| Claude uses Playwright MCP | Claude drives browser discovery in-session using Playwright MCP tools | ✓ |

**User's choice:** Claude uses Playwright MCP

**Follow-up — auth strategy:**

| Option | Description | Selected |
|--------|-------------|----------|
| Unauthenticated first | Try without auth; fall back to cookie if markets require login | ✓ |
| Use session cookie | Inject PINNACLE_SESSION_COOKIE immediately for authenticated view | |

**User's choice:** Unauthenticated first

**Follow-up — handoff after discovery:**

| Option | Description | Selected |
|--------|-------------|----------|
| Yes, review first | Stop after docs/pinnacle-api-notes.md, wait for user approval before writing client | ✓ |
| Proceed automatically | Write notes and immediately continue to data/odds.py | |

**User's choice:** Stop for user review after docs/pinnacle-api-notes.md

**Follow-up — if auth required:**

| Option | Description | Selected |
|--------|-------------|----------|
| Ask user for the cookie | Stop and ask user to provide PINNACLE_SESSION_COOKIE for the session | ✓ |
| Read from env directly | Read env var via Bash and inject automatically | |

**User's choice:** Ask user for the cookie

---

## OddsMarket Schema

| Option | Description | Selected |
|--------|-------------|----------|
| Minimal + IDs | rider names, decimal odds, race_name, matchup_id only | ✓ |
| Add start_time | Minimal + IDs plus start_time: datetime | |
| Full discovery | Include every Pinnacle field that could be useful | |

**User's choice:** Minimal + IDs

**Follow-up — dataclass vs TypedDict:**

| Option | Description | Selected |
|--------|-------------|----------|
| dataclass | Consistent with KellyResult; supports defaults, __repr__, type-safe access | ✓ |
| TypedDict | Better for dict-style JSON serialization | |
| You decide | Claude picks based on conventions | |

**User's choice:** dataclass

**Follow-up — matchup_id type:**

| Option | Description | Selected |
|--------|-------------|----------|
| str | Safe before discovery confirms type; no serialization surprises | ✓ |
| int | More precise if Pinnacle uses numeric IDs | |
| Decide after discovery | Claude sets type after inspecting real response | |

**User's choice:** str

---

## Odds Format

| Option | Description | Selected |
|--------|-------------|----------|
| Normalize to decimal in client | fetch_cycling_h2h_markets() always returns decimal; conversion in data/odds.py | ✓ |
| Pass through raw, convert in callers | OddsMarket stores raw format; Phase 4 or predictor converts | |

**User's choice:** Normalize to decimal in client

**Follow-up — audit log odds format:**

| Option | Description | Selected |
|--------|-------------|----------|
| Post-normalization decimal | Log what the client returns — clean decimal odds | ✓ |
| Pre-normalization raw | Log Pinnacle's raw American odds for fidelity | |
| Both | Log raw_odds_a/b and odds_a/b | |

**User's choice:** Post-normalization decimal

---

## Empty Market Behavior

| Option | Description | Selected |
|--------|-------------|----------|
| Return empty list | Return [] and let caller handle; no exception for empty results | ✓ |
| Raise PinnacleNoMarketsError | Distinct exception for empty vs auth failure | |

**User's choice:** Return empty list

**Follow-up — log empty fetches:**

| Option | Description | Selected |
|--------|-------------|----------|
| Log empty fetches too | Append JSONL line with markets: [] and metadata — complete audit trail | ✓ |
| Skip empty log entries | Only write when at least one market returned | |

**User's choice:** Log empty fetches too

---

## Deferred Ideas

- **Sortable batch prediction results** — user raised the idea of sorting batch H2H results by edge %, Kelly stake, win probability after running predictions. Redirected to Phase 5 (Frontend Integration).

