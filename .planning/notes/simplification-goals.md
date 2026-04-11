---
title: Simplification Goals — Feature Registry Pattern
date: 2026-04-10
context: Exploration session — pre-roadmap design intent
---

## What We're Solving

The current pipeline requires touching 4+ files to add or remove a single feature:
- `data/scraper.py` (if it's a new scraped field)
- `features/rider_features.py` or `features/race_features.py`
- `features/pipeline.py` — interaction logic duplicated in 3 separate places
  (`build_feature_vector`, `build_feature_vector_manual`, `build_feature_matrix`)

This makes experimentation expensive and error-prone.

## The Design Intent

A **feature registry**: a single Python config (dict or list at the top of one file)
where every feature is declared with its source, computation, and an enabled/disabled toggle.

The pipeline reads from the registry. Adding a feature means editing one file.
Removing a feature means flipping a toggle or deleting one entry. Claude edits
one file, not four — fast, cheap, reviewable.

## Constraints (Hard)

- **Stay simple.** A dict/list, not a plugin framework. No abstractions for their own sake.
- **No over-engineering.** The registry must be more navigable than what it replaces.
- **Code-level toggles only.** No runtime config, no UI — just edit the file.
- **Leakage prevention stays intact.** All features must still use pre-race data only.

## Sequencing

1. **Simplification first** — build the registry, eliminate duplication, clean up structure
2. **Feature engineering second** — add/remove data points on the clean foundation
3. **Model improvements third** — revisit NN/ensemble once signal quality is better

## Known Risks

- Scope creep on the simplification itself (building registry machinery > cleaning features)
- The registry becoming a new source of complexity if not kept flat and readable
