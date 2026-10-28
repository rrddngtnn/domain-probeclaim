"""Tests for core identity, store, and schedule modules."""
from __future__ import annotations

import random

from domain_probeclaim.core import schedule
from domain_probeclaim.core.identity import make_identity, redact
from domain_probeclaim.core.store import (add_account, add_domain, check_ip_budget,
                              counts, ip_history, log, open_db,
                              renew_queue, set_status, upsert_tenant)


def test_deterministic_identity():
    a, b = make_identity("seed-abc"), make_identity("seed-abc")
    assert a == b


def test_identity_variation_by_seed():
    a, c = make_identity("seed-abc"), make_identity("seed-xyz")
    assert a["email"] != c["email"]
    assert a["nama"] != c["nama"] or a["telepon"] != c["telepon"]


def test_identity_password_complexity():
    i = make_identity("x")
    assert len(i["password"]) >= 10
    assert any(ch.isdigit() for ch in i["password"])
    assert any(not ch.isalnum() for ch in i["password"])


def test_identity_redact():
    i = make_identity("x")
    r = redact(i)
    assert "password" not in r
    assert r["email"] == i["email"]


def test_identity_contact_fields():
    i = make_identity("x")
    for f in ("first_name", "last_name", "alamat", "kota", "provinsi", "kodepos"):
        assert i[f], f


def test_store_idempotent_schema(tmp_path):
    p = str(tmp_path / "a.db")
    db1, db2 = open_db(p), open_db(p)
    assert counts(db1)["accounts"] == 0
    assert counts(db2)["accounts"] == 0


def test_store_account_and_domain(db):
    tid = upsert_tenant(db, "t1", "mock")
    i = make_identity("s1")
    aid = add_account(db, tid, i, exit_ip="1.2.3.4")
    add_domain(db, aid, "a.example.test", "example.test",
               expires_at="2030-01-01", epp="E1")
    assert counts(db)["accounts"] == 1
    assert counts(db)["domains"] == 1
    assert db.execute("SELECT epp FROM domains").fetchone()["epp"] == "E1"


def test_store_status_validation(db):
    tid = upsert_tenant(db, "t", "mock")
    aid = add_account(db, tid, make_identity("s2"))
    set_status(db, aid, "active", "ok")
    assert db.execute("SELECT status FROM accounts WHERE id=?",
                      (aid,)).fetchone()["status"] == "active"
    try:
        set_status(db, aid, "invalid-status")
        assert False, "Unknown status must be rejected"
    except ValueError:
        pass


def test_store_event_logging(db):
    tid = upsert_tenant(db, "t", "mock")
    aid = add_account(db, tid, make_identity("s3"))
    log(db, aid, "test_event", "sample")
    kinds = [r["kind"] for r in db.execute(
        "SELECT kind FROM events WHERE account_id=?", (aid,))]
    assert "test_event" in kinds


def test_renew_queue_filtering(db):
    tid = upsert_tenant(db, "t", "mock")
    aid = add_account(db, tid, make_identity("s4"))
    add_domain(db, aid, "expired.example.test", "example.test", expires_at="2020-01-01")
    add_domain(db, aid, "future.example.test", "example.test", expires_at="2099-01-01")
    rq = [r["fqdn"] for r in renew_queue(db)]
    assert "expired.example.test" in rq
    assert "future.example.test" not in rq


def test_guard_ip_empty_allowed(db):
    ok, hist = check_ip_budget(db, "9.9.9.9", max_per_ip=2)
    assert ok and hist == []


def test_guard_ip_budget_enforcement(db):
    tid = upsert_tenant(db, "t", "mock")
    for n in range(2):
        add_account(db, tid, make_identity(f"g{n}"), exit_ip="9.9.9.9")
    ok2, hist2 = check_ip_budget(db, "9.9.9.9", max_per_ip=2)
    assert not ok2 and len(hist2) == 2
    ok3, _ = check_ip_budget(db, "9.9.9.9", max_per_ip=3)
    assert ok3


def test_guard_ip_ignores_dead_and_unrelated_ip(db):
    tid = upsert_tenant(db, "t", "mock")
    a = add_account(db, tid, make_identity("d1"), exit_ip="8.8.8.8")
    set_status(db, a, "dead")
    b = add_account(db, tid, make_identity("d2"), exit_ip="7.7.7.7")
    set_status(db, b, "active")
    ok, hist = check_ip_budget(db, "8.8.8.8", max_per_ip=1)
    assert ok and len(hist) == 0
    ok2, hist2 = check_ip_budget(db, "7.7.7.7", max_per_ip=1)
    assert not ok2 and len(hist2) == 1


def test_guard_ip_none_allowed(db):
    ok, hist = check_ip_budget(db, None, max_per_ip=1)
    assert ok and hist == []


def test_ip_history_window(db):
    tid = upsert_tenant(db, "t", "mock")
    add_account(db, tid, make_identity("w1"), exit_ip="6.6.6.6")
    assert len(ip_history(db, "6.6.6.6", days=7)) == 1
    assert len(ip_history(db, "6.6.6.6", days=0)) == 0


def test_jitter_variance():
    r = random.Random(1)
    d = [schedule.human_delay(1, 10, 0, rng=r) for _ in range(50)]
    assert max(d) - min(d) > 5


def test_rest_bonus_distribution():
    r = random.Random(99)
    bonus = [schedule.rest_bonus(0.5, 100, 200, rng=r) for _ in range(200)]
    assert any(b == 0 for b in bonus) and any(b > 0 for b in bonus)


def test_quiet_hours_boundaries():
    import datetime
    d = lambda h: datetime.datetime(2026, 1, 1, h, 0)
    assert schedule.in_quiet_hours(d(2))
    assert not schedule.in_quiet_hours(d(12))
    assert not schedule.in_quiet_hours(d(6))


def test_next_slots_ordering():
    r = random.Random(7)
    slots = schedule.next_slots(4, 100, 200, rng=r)
    assert all(slots[i] < slots[i + 1] for i in range(len(slots) - 1))
