# SECURITY.md

**Project:** PaceIQ — ml-cycling-predictor
**Phase:** 01 — Pinnacle API Discovery and Client (Plans 01-01, 01-02)
**ASVS Level:** 1
**Audited:** 2026-04-11
**Auditor:** gsd-security-auditor (claude-sonnet-4-6)

---

## Threat Verification

| Threat ID | Category | Component | Disposition | Status | Evidence |
|-----------|----------|-----------|-------------|--------|----------|
| T-01-02 | Information Disclosure | docs/pinnacle-api-notes.md | mitigate | CLOSED | No 32-char alphanumeric key value present in file. Env var name `PINNACLE_SESSION_COOKIE` referenced for user guidance only (lines 54, 61, 266). Grep for `[A-Za-z0-9]{32}` returns 0 matches. |
| T-02-01 | Information Disclosure | data/.pinnacle_key_cache | mitigate | CLOSED | `.gitignore` line 34: `data/.pinnacle_key_cache` — file is excluded from version control. |
| T-02-02 | Information Disclosure | data/odds_log.jsonl (audit log) | mitigate | CLOSED | `_append_audit_log()` (data/odds.py lines 273–301) builds record with only: `fetched_at`, `status`, `market_count`, `markets`, `error`. The `api_key` variable is scoped to `fetch_cycling_h2h_markets()` and is never passed to nor serialized by `_append_audit_log()`. |
| T-02-05 | Elevation of Privilege | PinnacleAuthError messages | mitigate | CLOSED | Three raise sites (lines 240–243, 263–266, 352–355). Each names `PINNACLE_SESSION_COOKIE` as the env var to set. The only f-string interpolation is `response.status_code` (HTTP numeric code). No key value is interpolated in any error message. |
| T-02-06 | Denial of Service | fetch_cycling_h2h_markets auth retry | mitigate | CLOSED | `retried = False` flag (line 329). First 401/403: cache invalidated, key re-extracted, `retried = True`, loop continues. Second 401/403: `if retried` branch raises `PinnacleAuthError` immediately (lines 349–355). Loop cannot execute a third attempt. |

**Threats Closed:** 5/5

---

## Accepted Risks Log

None in this phase. All threats are mitigated.

---

## Unregistered Threat Flags

No unregistered flags. Both SUMMARY files (`01-01-SUMMARY.md`, `01-02-SUMMARY.md`) reference only threat IDs already in the register (T-02-01, T-02-02, T-02-05, T-02-06). The 01-01-SUMMARY explicitly states no new threat surface was introduced.

---

## Scope Notes

This audit covers Phase 01, Plans 01-01 and 01-02 only:
- `docs/pinnacle-api-notes.md` — API contract document
- `data/odds.py` — Pinnacle cycling H2H market client
- `.gitignore` — key cache exclusion

Out of scope: Flask endpoints (Phase 4), model layer, scraper, P&L tracker.

---

## Implementation Notes

- The env var convention is `PINNACLE_SESSION_COOKIE` (not `PINNACLE_API_KEY`). The Plan 01-02 threat register uses `PINNACLE_API_KEY` in mitigation pattern descriptions; the implementation and 01-01 SUMMARY correctly applied the user-approved correction to `PINNACLE_SESSION_COOKIE`. Verification was performed against the actual implementation name.
- `data/odds_log.jsonl` is an append-only audit file. No integrity check is implemented (T-02-03, accepted in plan threat model — personal tool, no external verifier).
- JS bundle key extraction (`_extract_key_from_bundle`) fetches over HTTPS from `www.pinnacle.com`. Bundle source spoofing via MitM is accepted (T-02-04 in plan threat model — beyond scope for this tool).
