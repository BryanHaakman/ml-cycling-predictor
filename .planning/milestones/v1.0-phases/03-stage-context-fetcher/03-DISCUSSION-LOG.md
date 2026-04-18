# Phase 3: Stage Context Fetcher — Discussion Log

**Session:** 2026-04-12
**Mode:** Interactive (discuss)

---

## Area 1: Pinnacle → PCS Matching

**Q: How should a Pinnacle race name like 'Tour de France - Stage 12' get resolved to a PCS stage URL?**
Options: Cache.db + Race.stages() / Hardcoded name map + Race.stages() / Direct slug construction
→ **Selected: Cache.db + Race.stages()** — fuzzy match race name against cache.db, use Race.stages() to find today's stage by date. Fully dynamic, works for any race without manual maintenance.

**Q: Fallback when race isn't found in cache.db?**
Options: Return is_resolved=False immediately / Try PCS direct construction / Raise specific error type
→ **Selected: idk (user deferred)** — marked as Claude's discretion. Recommended default: `is_resolved=False` immediately.

**Q: How rigid should Pinnacle name parsing be?**
Options: Lenient + documented assumption / Strict match only / Defer to Phase 4
→ **Selected: Lenient + documented assumption** — build with documented assumption about format (e.g., `"RACE NAME - Stage N"`), make separator a named constant for easy adjustment after Phase 1 confirms real format.

---

## Area 2: Module Location & Style

**Q: Where should stage_context.py live?**
Options: intelligence/ package / data/ package
→ **Selected: intelligence/ package** — new directory, signals beginning of analysis layer. Matches ROADMAP.md.

**Q: Module-level function or class?**
Options: Module-level function / Class (like NameResolver)
→ **Selected: Module-level function** — stateless operation, no persistent state needed. Consistent with data/odds.py.

---

## Area 3: Cache.db Fallback Depth

**Q: When PCS is unreachable, attempt cache.db historical pre-fill before is_resolved=False?**
Options: No — manual input immediately / Yes — try cache.db for last edition
→ **Selected: No — manual input immediately** — historical data from past editions could silently mislead on changed routes. Clean fallback to manual input.

---

## Area 4: Missing Field Handling

**Q: When Stage.vertical_meters() returns None, what goes in StageContext?**
Options: Pass None through / Zero-fill before returning
→ **Selected: Pass None through** — build_feature_vector_manual already zero-fills with .get(). No duplicate fallback logic.

**Q: How should num_climbs be derived from Stage.climbs()?**
Options: len(climbs list) / Categorised only
→ **Selected: len(climbs list)** — count all climbs regardless of category. Matches how num_climbs is consumed downstream.

---

*Log generated: 2026-04-12*
