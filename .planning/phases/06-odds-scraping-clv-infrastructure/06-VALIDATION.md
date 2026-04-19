---
phase: 6
slug: odds-scraping-clv-infrastructure
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-18
---

# Phase 6 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x |
| **Config file** | tests/ directory (existing) |
| **Quick run command** | `pytest tests/ -x -q` |
| **Full suite command** | `pytest tests/ -v` |
| **Estimated runtime** | ~30 seconds |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/ -x -q`
- **After every plan wave:** Run `pytest tests/ -v`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 06-01-T1 | 06-01 | 1 | ODDS-01, ODDS-02, ODDS-03, ODDS-05 | T-06-01, T-06-02, T-06-03 | Parameterized SQL; browser cleanup; anti-bot delays | unit (mock page) | `pytest tests/test_pinnacle_scraper.py -x -v` | Wave 0 | pending |
| 06-01-T2 | 06-01 | 1 | CLV-01 | T-06-12 | Subprocess timeout; error logging | script | `python scripts/scrape_odds.py --help && python scripts/schedule_closing_odds.py --help` | N/A | pending |
| 06-02-T1 | 06-02 | 1 | CLV-01..05, CLV-07, BET-01..03 | T-06-04, T-06-05 | Parameterized queries; localhost-only | unit | `pytest tests/test_clv.py -x -v` | Wave 0 | pending |
| 06-03-T1 | 06-03 | 2 | ODDS-04, BET-01 | T-06-06, T-06-07 | Parameterized filters; _require_localhost | unit | `pytest tests/test_pinnacle_bp.py -x -v` | Existing | pending |
| 06-03-T2 | 06-03 | 2 | CLV-06 | T-06-06 | Parameterized queries | integration | `python -c "from webapp.app import app; c=app.test_client(); r=c.get('/api/pnl/clv-summary'); assert r.status_code==200"` | N/A | pending |
| 06-04-T1 | 06-04 | 3 | ODDS-04, BET-01 | T-06-08, T-06-09 | Server-side validation; localhost-only | static + integration | `python -c "from webapp.app import app; ...assert 'Book Bet' in content..."` (see plan) | N/A | pending |
| 06-04-CP | 06-04 | 3 | BET-01 | — | N/A | manual | Human verify booking flow in browser | N/A | pending |
| 06-05-T1 | 06-05 | 3 | CLV-06, CLV-07 | T-06-10, T-06-11 | Jinja2 auto-escaping; textContent for names | static | `python -c "...assert 'Avg CLV' in content..."` (see plan) | N/A | pending |
| 06-05-CP | 06-05 | 3 | CLV-06 | — | N/A | manual | Human verify CLV charts and cards in browser | N/A | pending |

*Status: pending · green · red · flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_pinnacle_scraper.py` — stubs for ODDS-01 through ODDS-05
- [ ] `tests/test_clv.py` — stubs for CLV-01 through CLV-07
- [ ] `tests/test_bet_recording.py` — stubs for BET-01 through BET-03
- [ ] Existing `tests/test_odds.py` will need updating (imports from deleted module)
- [ ] Existing `tests/test_pinnacle_bp.py` will need updating (mocks for new scraper)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Pinnacle.ca scrape returns live data | ODDS-01 | Requires live Pinnacle page with active markets | Run scraper with --headed, verify matchups appear |
| Bet booking UI flow | BET-01 | Frontend interaction (editable stake, confirmation dialog) | Open batch prediction page, adjust stake, click book, verify in DB |
| P&L CLV chart renders correctly | CLV-06 | Visual verification of Chart.js rendering | Open /pnl page, verify rolling CLV chart with sample data |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
