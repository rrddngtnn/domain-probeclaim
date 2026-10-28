"""Tes routing: proxy vs tanpa proxy. Ini yang diminta dipastikan.

Semua tes di sini memalsukan pengecekan IP, jadi tidak butuh jaringan.
Yang diuji adalah KEPUTUSAN routing dan konsekuensinya ke guard, bukan
konektivitas.
"""
from __future__ import annotations

import json

import pytest

from ramet.core import netpool


def fake_pool(tmp_path, entries):
    p = tmp_path / "proxies.json"
    p.write_text(json.dumps({"proxies": entries}))
    return netpool.ProxyPool(str(p))


# ---------------- mode direct ----------------
def test_direct_tanpa_pool(tmp_path):
    pool = netpool.ProxyPool(str(tmp_path / "tidak-ada.json"))
    route = netpool.resolve_route("seed", pool=pool, mode="direct",
                                  ip_checker=lambda: "10.0.0.1")
    assert route.mode == "direct"
    assert route.proxy is None
    assert route.exit_ip == "10.0.0.1"
    assert route.ok
    assert route.url() is None


def test_direct_budget_lebih_kecil_dari_pool(tmp_path):
    pool = fake_pool(tmp_path, [{"url": "http://u:p@h:1", "kind": "residential"}])
    direct = netpool.resolve_route("s", pool=pool, mode="direct",
                                   ip_checker=lambda: "10.0.0.1")
    assert direct.budget == netpool.DEFAULT_BUDGET["direct"]
    assert direct.budget < netpool.DEFAULT_BUDGET["pool"]


def test_direct_tetap_dapat_ip_untuk_guard(tmp_path):
    """Ini poin pentingnya: tanpa proxy bukan berarti tanpa jejak.
    exit_ip harus terisi supaya guard IP tetap bisa jalan."""
    pool = netpool.ProxyPool(str(tmp_path / "kosong.json"))
    called = []

    def checker():
        called.append(1)
        return "203.0.113.9"

    route = netpool.resolve_route("s", pool=pool, mode="direct", ip_checker=checker)
    assert route.exit_ip == "203.0.113.9"
    assert called, "ip_checker harus dipanggil walau tanpa proxy"


# ---------------- mode auto ----------------
def test_auto_jadi_direct_kalau_pool_kosong(tmp_path):
    pool = netpool.ProxyPool(str(tmp_path / "kosong.json"))
    route = netpool.resolve_route("s", pool=pool, mode="auto",
                                  ip_checker=lambda: "1.1.1.1")
    assert route.mode == "direct" and route.ok


def test_auto_jadi_pool_kalau_pool_isi(tmp_path, monkeypatch):
    pool = fake_pool(tmp_path, [{"url": "http://u:p@h:1", "kind": "residential"}])
    monkeypatch.setattr(pool, "check", lambda p, timeout=10: "5.5.5.5")
    route = netpool.resolve_route("s", pool=pool, mode="auto",
                                  ip_checker=lambda: "1.1.1.1")
    assert route.mode == "pool"
    assert route.proxy is not None
    assert route.exit_ip == "5.5.5.5"
    assert route.url() == "http://u:p@h:1"


# ---------------- mode pool wajib ----------------
def test_pool_wajib_gagal_kalau_kosong(tmp_path):
    pool = netpool.ProxyPool(str(tmp_path / "kosong.json"))
    route = netpool.resolve_route("s", pool=pool, mode="pool",
                                  ip_checker=lambda: "1.1.1.1")
    assert not route.ok
    assert "kosong" in (route.error or "")


def test_pool_wajib_gagal_kalau_proxy_mati(tmp_path, monkeypatch):
    pool = fake_pool(tmp_path, [{"url": "http://u:p@dead:1", "kind": "mobile"}])
    monkeypatch.setattr(pool, "check", lambda p, timeout=10: None)
    route = netpool.resolve_route("s", pool=pool, mode="pool")
    assert not route.ok
    assert "mati" in (route.error or "")


# ---------------- alokasi ----------------
def test_assign_deterministik_per_seed(tmp_path, monkeypatch):
    pool = fake_pool(tmp_path, [
        {"url": "http://u:p@a:1", "kind": "residential"},
        {"url": "http://u:p@b:2", "kind": "mobile"},
        {"url": "http://u:p@c:3", "kind": "datacenter"},
    ])
    a1 = pool.assign("seed-sama")
    a2 = pool.assign("seed-sama")
    assert a1 is a2 or a1["url"] == a2["url"]


def test_assign_menyebar_antar_seed(tmp_path):
    pool = fake_pool(tmp_path, [
        {"url": f"http://u:p@h{i}:1", "kind": "residential"} for i in range(6)
    ])
    picks = {pool.assign(f"seed-{i}")["url"] for i in range(40)}
    assert len(picks) > 1, "semua seed dapat proxy sama — alokasi rusak"


def test_pool_membaca_format_string_dan_dict(tmp_path):
    p = tmp_path / "p.json"
    p.write_text(json.dumps({"proxies": ["http://u:p@x:1",
                                         {"url": "http://u:p@y:2",
                                          "kind": "mobile"}]}))
    pool = netpool.ProxyPool(str(p))
    assert len(pool) == 2
    kinds = {v["kind"] for v in pool.by_id.values()}
    assert kinds == {"residential", "mobile"}


def test_pool_file_rusak_tidak_crash(tmp_path):
    p = tmp_path / "rusak.json"
    p.write_text("{bukan json")
    pool = netpool.ProxyPool(str(p))
    assert len(pool) == 0


# ---------------- sesi & fingerprint ----------------
def test_session_direct_tanpa_proxy():
    from ramet.core.httpses import session_for
    s, ua = session_for("s", None)
    assert ua.startswith("Mozilla/")
    assert not getattr(s, "proxies", None)


def test_session_pool_membawa_proxy():
    from ramet.core.httpses import session_for
    s, _ = session_for("s", {"url": "http://u:p@h:9"})
    proxies = getattr(s, "proxies", None) or {}
    assert proxies.get("https") == "http://u:p@h:9"


def test_ua_stabil_per_seed():
    from ramet.core.httpses import user_agent
    assert user_agent("a") == user_agent("a")
