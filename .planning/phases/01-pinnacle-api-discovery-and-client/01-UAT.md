---
status: complete
phase: 01-pinnacle-api-discovery-and-client
source: [01-01-SUMMARY.md, 01-02-SUMMARY.md]
started: 2026-04-11T00:00:00Z
updated: 2026-04-11T00:00:00Z
---

## Current Test

[testing complete]

## Tests

### 1. Module imports cleanly
expected: |
  Run: python -c "from data.odds import OddsMarket, PinnacleAuthError, fetch_cycling_h2h_markets; print('OK')"
  Should print "OK" with exit code 0. No ImportError, no circular import warnings.
result: pass

### 2. OddsMarket dataclass has correct fields
expected: |
  Run: python -c "import dataclasses, sys; sys.path.insert(0, '.'); from data.odds import OddsMarket; print([f.name for f in dataclasses.fields(OddsMarket)])"
  Should print: ['rider_a_name', 'rider_b_name', 'odds_a', 'odds_b', 'race_name', 'matchup_id']
  matchup_id must be type str (not int).
result: pass

### 3. American-to-decimal conversion
expected: |
  Run: python -c "import sys; sys.path.insert(0, '.'); from data.odds import _american_to_decimal; print(_american_to_decimal(107), _american_to_decimal(-154), _american_to_decimal(-100))"
  Should print: 2.07  1.6494  2.0
result: pass

### 4. Auth error names PINNACLE_SESSION_COOKIE
expected: |
  Run: python -c "
  import sys, os, unittest.mock; sys.path.insert(0, '.')
  from data.odds import _get_api_key, PinnacleAuthError
  with unittest.mock.patch.dict(os.environ, {}, clear=True):
    with unittest.mock.patch('data.odds._extract_key_from_bundle', return_value=None):
      try:
        _get_api_key()
      except PinnacleAuthError as e:
        print('ERROR MSG:', e)
  "
  Error message should contain "PINNACLE_SESSION_COOKIE" (not PINNACLE_API_KEY).
result: pass

### 5. Audit log writes valid JSONL
expected: |
  Run: python -c "
  import sys, os, json, tempfile; sys.path.insert(0, '.')
  import data.odds as m
  tmp = tempfile.mktemp(suffix='.jsonl')
  m.ODDS_LOG_PATH = tmp
  m._append_audit_log([], 'empty')
  line = open(tmp).readline()
  rec = json.loads(line)
  print('status:', rec['status'], '| markets:', rec['markets'], '| has fetched_at:', 'fetched_at' in rec)
  os.unlink(tmp)
  "
  Should print: status: empty | markets: [] | has fetched_at: True
result: pass

### 6. Full test suite passes
expected: |
  Run: pytest tests/ -v
  Should show 39 passed (25 from test_odds.py, 3 from test_builder_seed.py, 11 from test_export.py).
  Zero failures, zero errors. Warnings are OK.
result: pass

### 7. API notes document complete
expected: |
  Run: python -c "
  content = open('docs/pinnacle-api-notes.md').read()
  checks = ['guest.api.arcadia.pinnacle.com', 'X-Api-Key', '45', 'PINNACLE_SESSION_COOKIE', 'data/.pinnacle_key_cache', '1628017725', 'American']
  for c in checks: print('OK' if c in content else 'MISSING: '+c)
  "
  All lines should print "OK".
result: pass

### 8. Gitignore excludes key cache
expected: |
  Run: Select-String "pinnacle_key_cache" .gitignore
  Should return a match. data/.pinnacle_key_cache must never be committed.
result: pass

## Summary

total: 8
passed: 8
issues: 0
pending: 0
skipped: 0

## Gaps

[none yet]
