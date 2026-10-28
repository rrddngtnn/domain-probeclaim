"""Tests for network routing, proxy assignments, and direct mode fallback."""
from __future__ import annotations

import json

import pytest

from accfarm.core import netpool


def fake_pool(tmp_path, entries):
    p = tmp_path / "proxies.json"
    p.write_text(json.dumps({"proxies": entries}))
    return netpool.ProxyPool(str(p))


def test_direct_without_pool(tmp_path):
    pool = netpool.ProxyPool(str(tmp_path / "missing.json"))
    route = netpool.resolve_route("seed", pool=pool, mode="direct",
                                  ip_checker=lambda: "10.0.0.1")
    assert route.mode == "direct"
    assert route.proxy is None
    assert route.exit_ip == "10.0.0.1"
    assert route.ok
    assert route.url() is None


def test_direct_budget_smaller_than_pool(tmp_path):
    pool = fake_pool(tmp_path, [{"url": "http://u:p@h:1", "kind": "residential"}])
    direct = netpool.resolve_route("s", pool=pool, mode="direct",
                                   ip_checker=lambda: "10.0.0.1")
    assert direct.budget == netpool.DEFAULT_BUDGET["direct"]
    assert direct.budget < netpool.DEFAULT_BUDGET["pool"]


def test_direct_records_exit_ip_for_guard(tmp_path):
    pool = netpool.ProxyPool(str(tmp_path / "empty.json"))
    called = []

    def checker():
        called.append(1)
        return "203.0.113.9"

    route = netpool.resolve_route("s", pool=pool, mode="direct", ip_checker=checker)
    assert route.exit_ip == "203.0.113.9"
    assert called


def test_auto_fallback_to_direct_when_pool_empty(tmp_path):
    pool = netpool.ProxyPool(str(tmp_path / "empty.json"))
    route = netpool.resolve_route("s", pool=pool, mode="auto",
                                  ip_checker=lambda: "1.1.1.1")
    assert route.mode == "direct" and route.ok


def test_auto_uses_pool_when_populated(tmp_path, monkeypatch):
    pool = fake_pool(tmp_path, [{"url": "http://u:p@h:1", "kind": "residential"}])
    monkeypatch.setattr(pool, "check", lambda p, timeout=10: "5.5.5.5")
    route = netpool.resolve_route("s", pool=pool, mode="auto",
                                  ip_checker=lambda: "1.1.1.1")
    assert route.mode == "pool"
    assert route.proxy is not None
    assert route.exit_ip == "5.5.5.5"
    assert route.url() == "http://u:p@h:1"


def test_pool_mode_fails_if_empty(tmp_path):
    pool = netpool.ProxyPool(str(tmp_path / "empty.json"))
    route = netpool.resolve_route("s", pool=pool, mode="pool",
                                  ip_checker=lambda: "1.1.1.1")
    assert not route.ok
    assert "empty" in (route.error or "")


def test_pool_mode_fails_if_proxy_offline(tmp_path, monkeypatch):
    pool = fake_pool(tmp_path, [{"url": "http://u:p@dead:1", "kind": "mobile"}])
    monkeypatch.setattr(pool, "check", lambda p, timeout=10: None)
    route = netpool.resolve_route("s", pool=pool, mode="pool")
    assert not route.ok
    assert "offline" in (route.error or "")


def test_deterministic_assignment_per_seed(tmp_path, monkeypatch):
    pool = fake_pool(tmp_path, [
        {"url": "http://u:p@a:1", "kind": "residential"},
        {"url": "http://u:p@b:2", "kind": "mobile"},
        {"url": "http://u:p@c:3", "kind": "datacenter"},
    ])
    a1 = pool.assign("seed-fixed")
    a2 = pool.assign("seed-fixed")
    assert a1 is a2 or a1["url"] == a2["url"]


def test_assignment_distribution(tmp_path):
    pool = fake_pool(tmp_path, [
        {"url": f"http://u:p@h{i}:1", "kind": "residential"} for i in range(6)
    ])
    picks = {pool.assign(f"seed-{i}")["url"] for i in range(40)}
    assert len(picks) > 1


def test_pool_parses_string_and_dict_entries(tmp_path):
    p = tmp_path / "p.json"
    p.write_text(json.dumps({"proxies": ["http://u:p@x:1",
                                         {"url": "http://u:p@y:2",
                                          "kind": "mobile"}]}))
    pool = netpool.ProxyPool(str(p))
    assert len(pool) == 2
    kinds = {v["kind"] for v in pool.by_id.values()}
    assert kinds == {"residential", "mobile"}


def test_pool_handles_malformed_json(tmp_path):
    p = tmp_path / "corrupt.json"
    p.write_text("{invalid json")
    pool = netpool.ProxyPool(str(p))
    assert len(pool) == 0


def test_session_direct_without_proxy():
    from accfarm.core.httpses import session_for
    s, ua = session_for("s", None)
    assert ua.startswith("Mozilla/")
    assert not getattr(s, "proxies", None)


def test_session_pool_attaches_proxy():
    from accfarm.core.httpses import session_for
    s, _ = session_for("s", {"url": "http://u:p@h:9"})
    proxies = getattr(s, "proxies", None) or {}
    assert proxies.get("https") == "http://u:p@h:9"


def test_user_agent_stable_by_seed():
    from accfarm.core.httpses import user_agent
    assert user_agent("a") == user_agent("a")
