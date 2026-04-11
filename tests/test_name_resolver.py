"""Tests for data/name_resolver.py — name resolution pipeline."""

import os
import sys
import json
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from data.name_resolver import NameResolver, ResolveResult


class TestResolveResult:
  """Tests for ResolveResult dataclass contract (per D-03)."""

  def test_resolve_result_fields(self):
    """ResolveResult has all required fields per D-03."""
    r = ResolveResult(
      url="rider/test",
      best_candidate_url=None,
      best_candidate_name=None,
      best_score=None,
      method="exact",
    )
    assert r.url == "rider/test"
    assert r.method == "exact"
    assert r.best_candidate_url is None
    assert r.best_candidate_name is None
    assert r.best_score is None


class TestExactMatch:
  """Tests for NAME-01: exact match against cache.db riders."""

  def test_resolve_exact_match(self, tmp_path, monkeypatch):
    """A name that exactly matches a rider in cache.db returns that rider's URL."""
    # Isolate from real name_mappings.json
    cache_file = tmp_path / "name_mappings.json"
    monkeypatch.setattr("data.name_resolver.CACHE_PATH", str(cache_file))
    resolver = NameResolver()
    result = resolver.resolve("Primož Roglič")
    assert result.url == "rider/primoz-roglic"
    assert result.method == "exact"


class TestNormalizedMatch:
  """Tests for NAME-02: unicode normalization + word-order reversal."""

  @pytest.mark.parametrize("pinnacle_name,expected_url", [
    ("ROGLIC PRIMOZ", "rider/primoz-roglic"),
    ("VAN AERT WOUT", "rider/wout-van-aert"),
    ("BARDET ROMAIN", "rider/romain-bardet"),
    ("QUINTANA NAIRO", "rider/nairo-quintana"),
  ])
  def test_normalized_match_must_pass(self, pinnacle_name, expected_url, tmp_path, monkeypatch):
    """All four must-pass Pinnacle names resolve via normalization."""
    # Isolate from real name_mappings.json — each test gets a clean cache
    cache_file = tmp_path / "name_mappings.json"
    monkeypatch.setattr("data.name_resolver.CACHE_PATH", str(cache_file))
    resolver = NameResolver()
    result = resolver.resolve(pinnacle_name)
    assert result.url == expected_url, f"{pinnacle_name} -> {result}"
    assert result.method in ("normalized", "exact")


class TestCachePersistence:
  """Tests for NAME-04: persistent cache in data/name_mappings.json."""

  def test_resolve_cache_hit(self, tmp_path, monkeypatch):
    """A name present in name_mappings.json resolves via cache without DB query."""
    cache_file = tmp_path / "name_mappings.json"
    cache_file.write_text(json.dumps({"TEST RIDER": "rider/test-rider"}))
    monkeypatch.setattr("data.name_resolver.CACHE_PATH", str(cache_file))
    resolver = NameResolver()
    result = resolver.resolve("TEST RIDER")
    assert result.url == "rider/test-rider"
    assert result.method == "cache"

  def test_cache_persistence_after_accept(self, tmp_path, monkeypatch):
    """accept() writes to JSON; new NameResolver instance reads it back."""
    cache_file = tmp_path / "name_mappings.json"
    monkeypatch.setattr("data.name_resolver.CACHE_PATH", str(cache_file))
    resolver = NameResolver()
    resolver.accept("ACCEPTED NAME", "rider/accepted-rider")
    # New instance should find it in cache
    resolver2 = NameResolver()
    result = resolver2.resolve("ACCEPTED NAME")
    assert result.url == "rider/accepted-rider"
    assert result.method == "cache"

  def test_cache_invalid_entries_skipped(self, tmp_path, monkeypatch):
    """Invalid cache entries (bad URL pattern) are skipped, valid ones loaded."""
    cache_file = tmp_path / "name_mappings.json"
    cache_file.write_text(json.dumps({
      "GOOD": "rider/good-name",
      "BAD": "not-a-rider-url",
    }))
    monkeypatch.setattr("data.name_resolver.CACHE_PATH", str(cache_file))
    resolver = NameResolver()
    assert resolver.resolve("GOOD").url == "rider/good-name"
    assert resolver.resolve("BAD").url is None

  def test_cache_missing_file(self, tmp_path, monkeypatch):
    """Missing name_mappings.json does not crash — empty cache used."""
    cache_file = tmp_path / "nonexistent.json"
    monkeypatch.setattr("data.name_resolver.CACHE_PATH", str(cache_file))
    resolver = NameResolver()
    result = resolver.resolve("UNKNOWN NAME")
    assert result.url is None
