---
phase: 01
slug: pinnacle-api-discovery-and-client
status: verified
threats_open: 0
asvs_level: 1
created: 2026-04-11
---

# Phase 01 — Security

> Per-phase security contract: threat register, accepted risks, and audit trail.

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| executor → Pinnacle API | HTTP responses from guest.api.arcadia.pinnacle.com are untrusted; response shape may deviate from verified schema | JSON market data (public odds) |
| Pinnacle JS bundle → key extraction | Bundle content is third-party; regex must be defensive against format changes | X-Api-Key guest token (credential-like) |
| data/.pinnacle_key_cache → disk | Plain-text file containing the extracted guest token; gitignored | X-Api-Key guest token |
| PINNACLE_SESSION_COOKIE env var → process | Env var bypasses extraction; must not be logged in plaintext | X-Api-Key guest token |
| docs file → Plan 02 executor | pinnacle-api-notes.md is the single source of truth; errors here propagate to implementation | API contract (non-sensitive) |

---

## Threat Register

| Threat ID | Category | Component | Disposition | Mitigation | Status |
|-----------|----------|-----------|-------------|------------|--------|
| T-01-01 | Tampering | docs/pinnacle-api-notes.md | accept | File written from verified research; git tracks all changes. Low risk at doc stage. | closed |
| T-01-02 | Information Disclosure | X-Api-Key in docs/pinnacle-api-notes.md | mitigate | Notes document the extraction mechanism only — no actual key value present. Verified: regex `[A-Za-z0-9]{32}` returns 0 matches in the file. | closed |
| T-01-03 | Denial of Service | Pinnacle API rate limiting | accept | No live API calls made in Plan 01 — all content sourced from RESEARCH.md verified findings. | closed |
| T-02-01 | Information Disclosure | data/.pinnacle_key_cache on disk | mitigate | Added to .gitignore (line 34). File is plain text, world-readable on disk but never committed. Acceptable for personal tool. | closed |
| T-02-02 | Information Disclosure | PINNACLE_SESSION_COOKIE in data/odds_log.jsonl | mitigate | `_append_audit_log()` (data/odds.py:273–301) serializes only `fetched_at`, `status`, `market_count`, `markets`, `error`. API key is never passed to or included in the JSONL record. | closed |
| T-02-03 | Tampering | data/odds_log.jsonl | accept | Append-only JSONL per project convention (matches data/bets.csv). No integrity check required — personal tool, no external verifier. | closed |
| T-02-04 | Spoofing | Pinnacle JS bundle source | accept | Bundle fetched over HTTPS from www.pinnacle.com. MitM requires compromised CA — beyond threat model for this tool. | closed |
| T-02-05 | Elevation of Privilege | PinnacleAuthError message content | mitigate | All three raise sites (data/odds.py:240–243, 263–266, 352–355) name `PINNACLE_SESSION_COOKIE` as the env var to set. Only `response.status_code` (numeric) is interpolated — key value is never included. | closed |
| T-02-06 | Denial of Service | Auth retry loop in fetch_cycling_h2h_markets | mitigate | `retried = False` flag (data/odds.py:329–364): first 401/403 sets `retried = True` and retries once; second 401/403 hits `if retried` guard and raises `PinnacleAuthError` immediately. No third attempt possible. | closed |

*Status: open · closed*
*Disposition: mitigate (implementation required) · accept (documented risk) · transfer (third-party)*

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|
| AR-01-01 | T-01-01 | Doc file tampering is low risk; git history provides full audit trail | Bryan Haakman | 2026-04-11 |
| AR-01-02 | T-01-03 | Plan 01 makes no live API calls; rate limiting is not applicable | Bryan Haakman | 2026-04-11 |
| AR-02-01 | T-02-03 | Append-only JSONL is project convention; personal tool with no external verifier | Bryan Haakman | 2026-04-11 |
| AR-02-02 | T-02-04 | HTTPS + CA trust is the standard web security model; beyond scope for this tool | Bryan Haakman | 2026-04-11 |

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-04-11 | 9 | 9 | 0 | gsd-security-auditor (claude-sonnet-4-6) |

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-04-11
