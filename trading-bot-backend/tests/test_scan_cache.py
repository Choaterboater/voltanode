"""Tests for scan response cache."""

from api.scan_cache import cache_clear, cache_get, cache_set, make_key


def test_scan_cache_round_trip() -> None:
    cache_clear()
    key = make_key("scanner", asset_class="crypto", top=20)
    payload = {"asset_class": "crypto", "results": [], "elapsed_ms": 42}
    cache_set(key, payload)
    hit = cache_get(key)
    assert hit is not None
    assert hit["cached"] is True
    assert hit["cache_age_ms"] >= 0
    assert hit["results"] == []
    assert hit["elapsed_ms"] == 42


def test_scan_cache_nocache_bypass() -> None:
    cache_clear()
    key = make_key("squeeze", days_back=7)
    cache_set(key, {"results": [{"ticker": "GME"}]})
    assert cache_get(key, nocache=True) is None


def test_scan_cache_clear_prefix() -> None:
    cache_clear()
    cache_set(make_key("scanner", a=1), {"x": 1})
    cache_set(make_key("squeeze", a=1), {"x": 2})
    removed = cache_clear("scanner:")
    assert removed == 1
    assert cache_get(make_key("scanner", a=1)) is None
    assert cache_get(make_key("squeeze", a=1)) is not None
