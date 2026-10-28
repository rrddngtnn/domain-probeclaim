"""Integration tests verifying driver, mock server, and runner pipeline."""
from __future__ import annotations

import json
import random

import pytest

from accfarm.core import netpool
from accfarm.core.identity import make_identity
from accfarm.core.store import counts, open_db, upsert_tenant
from accfarm.drivers.base import Capabilities, GATES, RegistrarDriver
from accfarm.drivers.mock import MockDriver
from accfarm.mailbox import MockMailbox
from accfarm.probe.schema import classify, follow_missing, probe_fields
from accfarm.runner import run_account, run_batch


def test_mock_signup_and_me(client):
    r = client.post("/api/auth/signup",
                    json={"email": "a@b.test", "password": "securepassword123"})
    assert r.status_code == 201
    me = client.get("/api/auth/me").json()["user"]
    assert me["email"] == "a@b.test"
    assert me["email_verified"] is False


def test_mock_short_password_rejected(client):
    r = client.post("/api/auth/signup", json={"email": "a@b.test", "password": "x"})
    assert r.status_code == 400
    assert r.json()["error"] == "password_too_short"


def test_mock_duplicate_email_rejected(client):
    client.post("/api/auth/signup", json={"email": "a@b.test", "password": "securepassword1"})
    r = client.post("/api/auth/signup", json={"email": "a@b.test", "password": "securepassword1"})
    assert r.status_code == 409


def test_mock_claim_without_contact_rejected(client):
    client.post("/api/auth/signup", json={"email": "a@b.test", "password": "securepassword1"})
    r = client.post("/api/domains/register", json={"domain_name": "x.example.test"})
    assert r.status_code == 400
    assert r.json()["error"] == "missing_contact"


def test_mock_invalid_domain_name_rejected(client):
    client.post("/api/auth/signup", json={"email": "a@b.test", "password": "securepassword1"})
    for payload in ({"domain": "x.example.test"}, {"fqdn": "x.example.test"},
                    {"sld": "x", "tld": "example.test"}):
        r = client.post("/api/domains/register", json=payload)
        assert r.json()["error"] == "invalid_domain_name", payload


def test_mock_contact_without_label_rejected(client):
    client.post("/api/auth/signup", json={"email": "a@b.test", "password": "securepassword1"})
    contact = {"first_name": "A", "last_name": "B", "email": "a@b.test",
               "phone": "0812", "address1": "Jl", "city": "Kota",
               "state": "Prov", "postal_code": "10110"}
    r = client.post("/api/contacts", json={"contact": contact})
    assert r.json()["error"] == "missing_label"


def test_mock_complete_contact_accepted(client):
    client.post("/api/auth/signup", json={"email": "a@b.test", "password": "securepassword1"})
    contact = {"first_name": "A", "last_name": "B", "email": "a@b.test",
               "phone": "0812", "address1": "Jl", "city": "Kota",
               "state": "Prov", "postal_code": "10110"}
    r = client.post("/api/contacts", json={"contact": contact, "label": "Primary"})
    assert r.status_code == 201
    assert r.json()["id"] > 0


def test_mock_quota_per_account(client):
    client.post("/api/auth/signup", json={"email": "a@b.test", "password": "securepassword1"})
    contact = {"first_name": "A", "last_name": "B", "email": "a@b.test",
               "phone": "0812", "address1": "Jl", "city": "Kota",
               "state": "Prov", "postal_code": "10110"}
    client.post("/api/contacts", json={"contact": contact, "label": "Primary"})
    assert client.post("/api/domains/register",
                       json={"domain_name": "one.example.test"}).status_code == 201
    assert client.post("/api/domains/register",
                       json={"domain_name": "two.example.test"}).status_code == 201
    r = client.post("/api/domains/register", json={"domain_name": "three.example.test"})
    assert r.status_code == 402
    assert r.json()["error"] == "insufficient_balance"


def test_mock_domain_already_taken(client):
    client.post("/api/auth/signup", json={"email": "a@b.test", "password": "securepassword1"})
    contact = {"first_name": "A", "last_name": "B", "email": "a@b.test",
               "phone": "0812", "address1": "Jl", "city": "Kota",
               "state": "Prov", "postal_code": "10110"}
    client.post("/api/contacts", json={"contact": contact, "label": "Primary"})
    client.post("/api/domains/register", json={"domain_name": "same.example.test"})
    client.post("/api/auth/signup", json={"email": "c@d.test", "password": "securepassword1"})
    client.post("/api/contacts", json={"contact": {**contact, "email": "c@d.test"},
                                       "label": "Primary"})
    r = client.post("/api/domains/register", json={"domain_name": "same.example.test"})
    assert r.status_code == 409


def test_mock_unsupported_tld(client):
    client.post("/api/auth/signup", json={"email": "a@b.test", "password": "securepassword1"})
    r = client.post("/api/domains/register", json={"domain_name": "x.com"})
    assert r.status_code == 403
    assert r.json()["error"] == "tld_not_available"


def test_classify_body_formats():
    assert classify({"error": "missing_x"}) == "missing_x"
    assert classify(json.dumps({"error": "abc"})) == "abc"
    assert classify({"ok": True}) == "ok"
    assert classify("<html>") == "<html>"


def test_follow_missing_sequential_fill():
    order = ["first_name", "last_name", "email"]

    def call(payload):
        for f in order:
            if not payload.get(f):
                return 400, {"error": f"missing_{f}"}
        return 201, {"id": 1}

    status, payload, body = follow_missing(
        call, {}, {"first_name": "A", "last_name": "B", "email": "a@b"})
    assert status == 201
    assert all(payload.get(f) for f in order)


def test_probe_fields_differential_detection():
    def call(payload):
        if "domain_name" in payload:
            return 400, {"error": "missing_contact"}
        return 400, {"error": "invalid_domain_name"}

    base, found = probe_fields(call, ["domain", "domain_name", "fqdn"],
                               "x.test")
    assert base == "invalid_domain_name"
    assert "domain_name" in found


def test_mock_mailbox_inject_and_wait():
    box_backend = MockMailbox()
    box = box_backend.create("seed-abc")
    box_backend.inject(box.address, "no-reply@site", "Verification",
                       "Link: https://site/verify?token=ABC123")
    hit, msg = box_backend.wait_for(box, r"token=([A-Z0-9]+)", timeout=2, poll=0.05)
    assert hit == "ABC123"
    assert msg.subject == "Verification"


def test_mock_mailbox_timeout_when_empty():
    b = MockMailbox()
    box = b.create("seed-x")
    hit, msg = b.wait_for(box, r"(\d{6})", timeout=0.3, poll=0.05)
    assert hit is None and msg is None


def test_driver_base_unusable_directly():
    d = RegistrarDriver()
    with pytest.raises(NotImplementedError):
        _ = d.caps


def test_capabilities_unattended():
    assert Capabilities(payment="qris", gate="email").unattended()
    assert not Capabilities(payment="card", gate="email").unattended()
    assert not Capabilities(payment="none", gate="kyc").unattended()
    assert not Capabilities(payment="none", gate="3ds").unattended()


def test_gates_complete():
    for k in ("none", "email", "kyc", "3ds", "captcha", "manual_review"):
        assert k in GATES


def test_driver_describe():
    d = MockDriver()
    info = d.describe()
    assert info["name"] == "mock"
    assert info["payment"] == "none"
    assert info["unattended"] is True


def _patch_session(monkeypatch, client):
    class FakeSession:
        def __init__(self, c):
            self.c = c

        @staticmethod
        def _path(url):
            return "/" + url.split("/", 3)[-1]

        def post(self, url, **kw):
            body = kw.get("data")
            try:
                payload = json.loads(body) if isinstance(body, (str, bytes)) else body
            except ValueError:
                payload = None
            return self.c.post(self._path(url), json=payload,
                               headers=kw.get("headers"))

        def get(self, url, **kw):
            return self.c.get(self._path(url), headers=kw.get("headers"),
                              params=kw.get("params"))

    import accfarm.runner as runner_mod
    monkeypatch.setattr(runner_mod, "session_for",
                        lambda seed, proxy=None, **kw: (FakeSession(client), "ua"))
    return FakeSession


def test_runner_mode_direct_full_lifecycle(monkeypatch, client, db):
    _patch_session(monkeypatch, client)
    tid = upsert_tenant(db, "mock", "mock")
    route = netpool.resolve_route("s", mode="direct", ip_checker=lambda: "10.1.1.1")
    res = run_account(db, MockDriver, tid, seed="run-direct-1",
                      route=route, mailbox=MockMailbox())
    assert res["mode"] == "direct"
    assert res["claimed"], res
    assert res["expires"], res
    assert counts(db)["domains"] == 1


def test_runner_mode_direct_guard_triggered(monkeypatch, client, db):
    _patch_session(monkeypatch, client)
    tid = upsert_tenant(db, "mock", "mock")
    route = netpool.resolve_route("s", mode="direct", ip_checker=lambda: "10.2.2.2")
    r1 = run_account(db, MockDriver, tid, seed="guard-1", route=route,
                     mailbox=MockMailbox(), max_per_ip=1)
    assert r1.get("claimed")
    r2 = run_account(db, MockDriver, tid, seed="guard-2", route=route,
                     mailbox=MockMailbox(), max_per_ip=1)
    assert r2.get("error") == "ip_guard"


def test_runner_mode_pool_routes_via_proxy(tmp_path, monkeypatch, client, db):
    p = tmp_path / "p.json"
    p.write_text(json.dumps({"proxies": [{"url": "http://u:p@h:1",
                                          "kind": "residential"}]}))
    pool = netpool.ProxyPool(str(p))
    monkeypatch.setattr(pool, "check", lambda pr, timeout=10: "5.5.5.5")
    _patch_session(monkeypatch, client)
    tid = upsert_tenant(db, "mock", "mock")
    route = netpool.resolve_route("s", pool=pool, mode="auto")
    res = run_account(db, MockDriver, tid, seed="pool-1", route=route,
                      mailbox=MockMailbox())
    assert res["mode"] == "pool"
    assert res["exit_ip"] == "5.5.5.5"
    assert res["claimed"]


def test_runner_dry_run_preserves_state(db):
    from accfarm.core.store import counts as c
    tid = upsert_tenant(db, "mock", "mock")
    route = netpool.resolve_route("s", mode="direct", ip_checker=lambda: "10.9.9.9")
    res = run_account(db, MockDriver, tid, seed="dry-1", route=route,
                      mailbox=MockMailbox(), dry_run=True)
    assert res.get("dry_run")
    assert c(db)["domains"] == 0


def test_runner_batch_stops_at_guard(monkeypatch, client, db):
    _patch_session(monkeypatch, client)
    tid = upsert_tenant(db, "mock", "mock")
    route = netpool.resolve_route("s", mode="direct", ip_checker=lambda: "10.3.3.3")
    out = run_batch(db, MockDriver, tid, count=4, route=route,
                    mailbox=MockMailbox(), max_per_ip=2, no_sleep=True)
    assert len(out) == 3
    assert out[-1].get("error") == "ip_guard"
