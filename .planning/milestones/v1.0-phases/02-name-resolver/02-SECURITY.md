# Security Audit — Phase 02: Name Resolver

**Phase:** 02 — name-resolver
**Audit Date:** 2026-04-11
**ASVS Level:** 1
**Auditor:** gsd-secure-phase
**Implementation Files Audited:**
- `data/name_resolver.py`

---

## Result: SECURED

**Threats Closed:** 6/6
**Threats Open:** 0/6

---

## Threat Verification

| Threat ID | Category | Disposition | Evidence |
|-----------|----------|-------------|----------|
| T-2-01 | Tampering | mitigate | `data/name_resolver.py:34` — `CACHE_URL_PATTERN = re.compile(r"^rider/[a-z0-9-]+$")`; applied at `line 261` inside `_load_cache()` — every value in `name_mappings.json` is validated on load; invalid entries are logged and skipped |
| T-2-02 | Denial of Service | mitigate | `data/name_resolver.py:275,284` — `_save_cache()` uses `tempfile.NamedTemporaryFile` + `os.replace(tmp_path, CACHE_PATH)`; atomic write prevents partial/corrupt state on crash or disk-full |
| T-2-03 | Information Disclosure | accept | Log output contains only PCS rider names and URLs (public data). No credentials, API keys, or PII are passed to `log.warning` or `log.info` calls. See accepted risks log below. |
| T-2-04 | Tampering | accept | Pinnacle name strings are used only as dict keys and as the query argument to `process.extractOne`. `get_db()` is called once in `__init__()` with no user-supplied SQL. No path traversal: cache values are validated by `CACHE_URL_PATTERN` before use; keys are dict keys stored in JSON only. See accepted risks log below. |
| T-2-05 | Spoofing | mitigate | `data/name_resolver.py:32` — `AUTO_ACCEPT_THRESHOLD = 90`; `line 191` — `scorer=fuzz.token_sort_ratio` (order-invariant); `line 198` — `if score_int >= AUTO_ACCEPT_THRESHOLD` gates auto-accept; scores 60-89 return hint only (`url=None`), requiring manual confirmation |
| T-2-06 | Information Disclosure | accept | `best_candidate_name` and `best_candidate_url` fields in `ResolveResult` expose PCS rider names and URLs. These are public data on procyclingstats.com. No PII risk. See accepted risks log below. |

---

## Accepted Risks Log

| Threat ID | Category | Rationale | Owner |
|-----------|----------|-----------|-------|
| T-2-03 | Information Disclosure | Log output is limited to PCS rider names (public data) and file paths. No credentials, tokens, or personal data are logged. Risk accepted at ASVS Level 1. | Bryan Haakman |
| T-2-04 | Tampering | Pinnacle name input is not used in SQL queries (`get_db()` is called only once at `__init__()` with a hardcoded `SELECT url, name FROM riders` query). Input is used only as a dict key and fuzzy-match query string. No path traversal is possible because cache values are validated by `CACHE_URL_PATTERN` and keys are stored as JSON string values only. Risk accepted at ASVS Level 1. | Bryan Haakman |
| T-2-06 | Information Disclosure | `ResolveResult.best_candidate_name` and `best_candidate_url` are populated from the PCS riders corpus and exposed to Phase 4/5 callers as a UI hint. PCS rider names and profile URLs are publicly accessible on procyclingstats.com. No PII risk. Risk accepted at ASVS Level 1. | Bryan Haakman |

---

## Unregistered Threat Flags

None. Neither `02-01-SUMMARY.md` nor `02-02-SUMMARY.md` declared new attack surface in a `## Threat Flags` section. Both executor threat surface scans explicitly confirmed no new network endpoints, auth paths, or file access patterns beyond the registered threat model.

---

## Audit Notes

- `CACHE_URL_PATTERN` regex (`^rider/[a-z0-9-]+$`) is intentionally strict: it rejects values with uppercase letters, path separators, query strings, or any non-alphanumeric characters other than hyphens. This prevents URL injection via a manually edited `name_mappings.json`.
- The atomic write in `_save_cache()` includes an `OSError` catch that logs a warning on failure rather than raising. This is acceptable at ASVS Level 1: a failed cache write degrades to in-memory-only resolution for the current session, which is not a security risk.
- `get_db()` is called in `__init__()` only. The DB connection is closed immediately after the bulk `SELECT` (`conn.close()` at line 128). No user input reaches the DB layer.
