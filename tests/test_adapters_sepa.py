"""Tests for pluggable adapter layer, SEPA generator, payment/gate flexibility, and cfast client."""
from __future__ import annotations

import json

import pytest

from domain_probeclaim.adapters import (
    CardPayment,
    CfastClearanceTransport,
    CfastClient,
    ChainConfig,
    CompositeGate,
    EmailGate,
    ManualGate,
    SepaPayment,
    TurnstileGate,
    VoucherPayment,
    build_chain,
    explain_chain,
    luhn_valid,
)
from domain_probeclaim.core import netpool
from domain_probeclaim.core.httpses import session_for
from domain_probeclaim.core.identity import make_identity
from domain_probeclaim.core.sepa import (
    format_iban,
    generate_iban,
    generate_sepa_profile,
    validate_iban,
)
from domain_probeclaim.core.store import counts, upsert_tenant
from domain_probeclaim.drivers.base import Capabilities
from domain_probeclaim.drivers.mock import MockDriver
from domain_probeclaim.drivers.rdap import RdapDriver
from domain_probeclaim.mailbox import MockMailbox
from domain_probeclaim.runner import run_account


@pytest.mark.parametrize("country", ["DE", "NL", "FR", "AT"])
def test_sepa_iban_deterministic_and_mod97_valid(country):
    a = generate_iban("seed-sepa-1", country=country)
    b = generate_iban("seed-sepa-1", country=country)
    assert a == b
    assert a["valid"] is True
    assert validate_iban(a["iban"])
    assert validate_iban(format_iban(a["iban"]))
    # Corrupt check digit must fail mod-97
    bad = a["iban"][:2] + ("00" if a["iban"][2:4] != "00" else "99") + a["iban"][4:]
    assert not validate_iban(bad)


def test_sepa_profile_includes_mandate():
    p = generate_sepa_profile("s1", holder="Lukas Mueller", country="DE")
    assert p["account_holder"] == "Lukas Mueller"
    assert p["mandate_ref"].startswith("MND-DE-")
    assert p["bic"]


def test_de_identity_locale():
    i = make_identity("de-seed-1", locale="de")
    assert i["country"] == "DE"
    assert i["telepon"].startswith("+49")
    assert len(i["kodepos"]) == 5


def test_voucher_payment_rotation_and_exhaustion():
    vp = VoucherPayment(codes=["PROMO1", "PROMO2"])
    assert vp.available()
    r1 = vp.run({"seed": "a"})
    r2 = vp.run({"seed": "b"})
    r3 = vp.run({"seed": "c"})
    assert r1.ok and r1.data["voucher"] == "PROMO1"
    assert r2.ok and r2.data["voucher"] == "PROMO2"
    assert not r3.ok


def test_sepa_payment_adapter_auto_and_override():
    sp = SepaPayment(country="DE")
    res = sp.run({"seed": "pay-1", "ident": {"nama": "Jonas Weber"}})
    assert res.ok
    assert validate_iban(res.data["sepa"]["iban"])

    bad = SepaPayment(override={"iban": "DE00100100101234567890", "bic": "PBNKDEFF"})
    assert not bad.available()


def test_card_payment_flexible_levels_and_luhn():
    assert CardPayment().level == 0
    assert luhn_valid("4111111111111111")
    assert not luhn_valid("4111111111111112")

    # Provider + 3DS callback -> level 1 (assisted) and runs cleanly
    cp = CardPayment(
        provider=lambda ctx: {"number": "4111111111111111", "exp": "12/29", "cvc": "123"},
        on_3ds=lambda ctx: {"otp": "654321"},
    )
    assert cp.level == 1
    res = cp.run({"seed": "c1"})
    assert res.ok
    assert res.data["payment"]["three_ds"]["otp"] == "654321"

    bad_cp = CardPayment(cards=[{"number": "4111111111111112"}])
    assert not bad_cp.run({"seed": "c2"}).ok


def test_turnstile_gate_syncs_cfast_ua_and_proxy(monkeypatch):
    captured = {}

    class FakeResp:
        def json(self):
            return {
                "status": 1,
                "token": "1.cf_token_mock",
                "ua": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) AppleWebKit/605.1.15 Safari/604.1",
                "elapsed": 1.2,
            }

    def fake_post(url, json=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        return FakeResp()

    import domain_probeclaim.adapters.solvers.cfast as cfast_mod
    monkeypatch.setattr(cfast_mod.requests, "post", fake_post)

    sess, _ = session_for("ua-sync")
    assert "Sec-Ch-Ua" in sess.headers
    route = netpool.Route("pool", {"url": "http://u:p@1.2.3.4:8080", "kind": "residential"},
                          "1.2.3.4", 3, 7)

    client = CfastClient(api_url="http://127.0.0.1:8810")
    gate = TurnstileGate(client)
    res = gate.run({
        "captcha_url": "https://target.example/signup",
        "sitekey": "0x4AAAAAAA",
        "route": route,
        "session": sess,
    })
    assert res.ok
    assert res.data["captcha_token"] == "1.cf_token_mock"
    assert captured["json"]["proxy"] == "http://u:p@1.2.3.4:8080"
    assert "iPhone" in sess.headers["User-Agent"]
    assert "Sec-Ch-Ua" not in sess.headers


def test_cfast_clearance_transport_injects_cookie(tmp_path, monkeypatch):
    bin_f = tmp_path / "challenge"
    bin_f.write_text("#!/bin/sh\n")
    prof_f = tmp_path / "profile.json"
    prof_f.write_text(json.dumps({
        "transport": {"headers": {"User-Agent": "Mozilla/5.0 (iPhone) Safari/604.1"}}
    }))

    class FakeProc:
        stdout = "checking...\ncf_clearance=clr_abc123\n"
        stderr = ""

    import domain_probeclaim.adapters.solvers.cfast as cfast_mod
    monkeypatch.setattr(cfast_mod.subprocess, "run", lambda *a, **kw: FakeProc())

    client = CfastClient(api_url=None, bin_path=str(bin_f), profile_path=str(prof_f))
    tr = CfastClearanceTransport(client, target_url="https://protected.example/")
    assert tr.available()
    ctx = {"seed": "clr-1", "route": None, "base_url": "https://protected.example/"}
    sess, ua = tr.open_session("clr-1", base_url="https://protected.example/", ctx=ctx)
    assert "Safari/604.1" in ua
    assert sess.cookies.get("cf_clearance") == "clr_abc123"


def test_build_chain_across_battlefields():
    # 1. Blocked checkdomain-style without solver/card
    c_block = build_chain(Capabilities(payment="card", gate="captcha"))
    assert not c_block.ok
    assert "BLOCKED" in explain_chain(c_block)

    # 2. Unblocked checkdomain-style with solver + SEPA + locale=de
    c_sepa = build_chain(
        Capabilities(payment="sepa", gate="captcha", captcha_kind="recaptcha_v2", locale="de"),
        config=ChainConfig(solver_url="http://127.0.0.1:8810", sepa_country="DE"),
    )
    assert c_sepa.ok and c_sepa.unattended

    # 3. Turnstile + Voucher
    c_turn = build_chain(
        Capabilities(payment="voucher", gate="turnstile"),
        config=ChainConfig(solver_url="http://127.0.0.1:8810", vouchers=["FREE100"]),
    )
    assert c_turn.ok and c_turn.unattended

    # 4. Card + 3DS assisted
    c_card = build_chain(
        Capabilities(payment="card", gate="email"),
        mailbox=MockMailbox(),
        config=ChainConfig(
            cards=[{"number": "4111111111111111"}],
            on_3ds=lambda ctx: "ok",
        ),
    )
    assert c_card.ok and c_card.assisted and not c_card.unattended


def test_composite_gate():
    g = CompositeGate([
        ManualGate("captcha", on_challenge=lambda ctx: {"captcha_token": "tok"}),
        EmailGate(MockMailbox()),
    ])
    assert g.level == 1
    res = g.run({"seed": "comp-1"})
    assert res.ok and res.data["captcha_token"] == "tok"


def _local_patch_session(monkeypatch, client):
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

    import domain_probeclaim.runner as runner_mod
    monkeypatch.setattr(runner_mod, "session_for",
                        lambda seed, proxy=None, **kw: (FakeSession(client), "ua"))


def test_runner_with_chain_config_sepa_and_de_locale(monkeypatch, client, db):
    _local_patch_session(monkeypatch, client)

    tid = upsert_tenant(db, "mock-sepa", "mock", payment="sepa")
    route = netpool.resolve_route("s", mode="direct", ip_checker=lambda: "10.8.8.8")
    cfg = ChainConfig(locale="de", payment_override="sepa", sepa_country="DE")
    res = run_account(db, MockDriver, tid, seed="de-sepa-1",
                      route=route, mailbox=MockMailbox(),
                      quiet_hours=False, chain_config=cfg)
    assert res["claimed"]
    assert res["unattended_ok"] is True
    assert counts(db)["domains"] == 1
    kinds = {r["kind"] for r in db.execute("SELECT kind FROM events")}
    assert {"gate", "payment", "claim"} <= kinds


def test_runner_rdap_readonly(monkeypatch, db):
    class FakeResp:
        def __init__(self, code):
            self.status_code = code
        def json(self):
            return {"ldhName": "taken.example"}

    class FakeSession:
        def get(self, url, timeout=20):
            return FakeResp(200 if "taken.com" in url else 404)

    import domain_probeclaim.runner as runner_mod
    monkeypatch.setattr(runner_mod, "session_for", lambda *a, **kw: (FakeSession(), "ua"))

    tid = upsert_tenant(db, "rdap", "rdap", payment="none")
    route = netpool.resolve_route("s", mode="direct", ip_checker=lambda: "10.7.7.7")
    cfg = ChainConfig(claim_mode="readonly", targets=["taken.com", "free-xyz-999.com"])
    res = run_account(db, RdapDriver, tid, seed="rdap-1", route=route,
                      quiet_hours=False, chain_config=cfg)
    assert res["claimed"] == "free-xyz-999.com"
    assert len(res["probes"]) == 2
    assert counts(db)["accounts"] == 0


def test_cli_cards_and_vouchers_files(tmp_path):
    from domain_probeclaim.cli import build_parser, _config_from_args
    vf = tmp_path / "vouchers.txt"
    vf.write_text("# comment\nPROMO-A\nPROMO-B\n")
    cf = tmp_path / "cards.json"
    cf.write_text(json.dumps([{"number": "4111111111111111", "exp": "12/29"}]))
    args = build_parser().parse_args([
        "chain", "--payment", "card", "--gate", "none",
        "--vouchers-file", str(vf), "--cards-file", str(cf),
    ])
    cfg = _config_from_args(args)
    assert cfg.vouchers == ["PROMO-A", "PROMO-B"]
    assert len(cfg.cards) == 1
    chain = build_chain(Capabilities(payment="card", gate="none"), config=cfg)
    assert chain.ok and chain.assisted

