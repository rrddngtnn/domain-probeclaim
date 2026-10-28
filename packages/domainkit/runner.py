"""domainkit.runner — orkestrasi: satu akun dari seed sampai domain.

Ini satu-satunya tempat yang menyatukan route (proxy/tanpa), driver, store,
mailbox, dan guard IP. Driver tidak tahu soal proxy; netpool tidak tahu
soal driver.

Urutan langkah sengaja eksplisit supaya bisa dihentikan di titik mana pun
dan dicatat ke `events`.
"""
from __future__ import annotations

import datetime
import random

from .core import netpool, schedule
from .core.httpses import session_for
from .core.identity import make_identity
from .core.store import (add_account, add_domain, check_ip_budget, log,
                         set_status)
from .drivers.base import GATES, RegistrarDriver


DEFAULT_GAPS = {"min": 1500, "max": 4500, "rest_chance": 0.2}


class RunResult(dict):
    def ok(self):
        return self.get("claimed") is not None


def new_seed(i: int = 0) -> str:
    return datetime.datetime.now().strftime("%Y%m%d%H%M%S") + f"-{i}"


def run_account(db, driver_cls, tenant_id, seed=None, route=None,
                mailbox=None, max_per_ip=3, ip_window_days=7,
                quiet_hours=True, dry_run=False, proxy_mode="auto",
                pool=None, rng=None, uid_label=None):
    """Buat satu akun dan (kalau driver mendukung) klaim satu domain.

    Return RunResult dengan kunci: seed, account_id, email, mode, exit_ip,
    verified, claimed, expires, epp, error.
    """
    r = rng or random.Random(seed)
    seed = seed or new_seed()
    res = RunResult(seed=seed, mode=None, exit_ip=None)

    if quiet_hours and schedule.in_quiet_hours():
        log(db, 0, "skip", f"quiet_hours seed={seed}")
        return RunResult(res, error="quiet_hours")

    # ---- routing: satu-satunya tempat proxy diputuskan
    route = route or netpool.resolve_route(seed, pool=pool, mode=proxy_mode)
    res["mode"], res["exit_ip"] = route.mode, route.exit_ip
    if not route.ok:
        log(db, 0, "route_fail", route.error)
        return RunResult(res, error=route.error)

    # ---- guard IP: berlaku sama untuk direct maupun pool
    allowed, hist = check_ip_budget(db, route.exit_ip, max_per_ip, ip_window_days)
    if not allowed:
        log(db, 0, "ip_guard",
            f"{route.exit_ip} sudah {len(hist)} akun/{ip_window_days}h "
            f"(batas {max_per_ip})")
        return RunResult(res, error="ip_guard", existing=len(hist))

    # ---- identitas + inbox
    ident = make_identity(seed)
    if mailbox is not None:
        box = mailbox.create(seed)
        ident["email"] = box.address
        ident["email_token"] = box.token

    # Server lokal tanpa TLS tidak paham `Upgrade: h2c`; paksa HTTP/1.1
    # hanya untuk target http://. Untuk https:// biarkan ALPN normal.
    base = getattr(driver_cls, "base_url", "") or ""
    http_ver = "v1" if base.startswith("http://") else None
    session, ua = session_for(seed, route.proxy, http_version=http_ver)
    driver = driver_cls(route=route, session=session, mailbox=mailbox,
                        db=db, dry_run=dry_run)
    res["driver"], res["unadattended_ok"] = driver.name, driver.caps.unattended()

    acc_id = add_account(db, tenant_id, ident, route.url(), route.exit_ip)
    res["account_id"], res["email"] = acc_id, ident["email"]
    log(db, acc_id, "route", f"mode={route.mode} ip={route.exit_ip} ua={ua[:36]}")

    # ---- signup
    try:
        out = driver.signup(ident)
        log(db, acc_id, "signup", str(out)[:200])
    except NotImplementedError:
        return RunResult(res, error="driver tanpa signup")
    except Exception as e:
        set_status(db, acc_id, "dead", "signup error")
        log(db, acc_id, "signup_fail", repr(e)[:300])
        return RunResult(res, error=f"signup: {e}")

    if dry_run:
        set_status(db, acc_id, "pending", "dry_run")
        return RunResult(res, dry_run=True)

    schedule.sleep_human(3, 9, rng=r)

    # ---- kontak WHOIS
    contact_ok = True
    try:
        c = driver.save_contact(ident)
        log(db, acc_id, "contact", str(c)[:200])
    except NotImplementedError:
        contact_ok = False
    except Exception as e:
        contact_ok = False
        log(db, acc_id, "contact_fail", repr(e)[:300])

    # ---- klaim
    claimed = None
    if driver.caps.claim and contact_ok:
        fqdn = _pick_fqdn(seed, driver)
        try:
            cr = driver.claim(fqdn)
            log(db, acc_id, "claim",
                f"{'ok' if cr.ok else 'fail'} {cr.fqdn} {cr.error or ''}"
                f" exp={cr.expires_at}")
            if cr.ok:
                add_domain(db, acc_id, cr.fqdn, _tld(cr.fqdn),
                           expires_at=cr.expires_at, epp=cr.epp)
                claimed = cr.fqdn
                res.update(claimed=cr.fqdn, expires=cr.expires_at, epp=cr.epp)
        except Exception as e:
            log(db, acc_id, "claim_fail", repr(e)[:300])

    set_status(db, acc_id, "active" if contact_ok else "pending",
               f"claimed={claimed}")
    return RunResult(res)


def _tld(fqdn: str) -> str:
    parts = fqdn.split(".", 1)
    return parts[1] if len(parts) == 2 else ""


def _pick_fqdn(seed: str, driver: RegistrarDriver) -> str:
    """Nama ber-seed. Bukan pola <kata>01/02 — itu satu cluster."""
    import hashlib
    rng = random.Random(hashlib.sha256(("fqdn" + seed).encode()).digest())
    kata = ["projek", "arsip", "catatan", "studio", "bengkel", "gudang",
            "simpul", "akar", "layar", "peta", "laci", "pojok"]
    tld = getattr(driver, "default_tld", "example.test")
    return f"{rng.choice(kata)}{rng.randint(1000, 99999)}.{tld}"


def run_batch(db, driver_cls, tenant_id, count=1, gaps=None, no_sleep=False,
              **kw):
    """Jalankan beberapa akun dengan jeda. Berhenti kalau guard menolak."""
    g = dict(DEFAULT_GAPS, **(gaps or {}))
    out = []
    for i in range(count):
        res = run_account(db, driver_cls, tenant_id, seed=new_seed(i), **kw)
        out.append(res)
        if res.get("error") in ("ip_guard", "quiet_hours"):
            break
        if i < count - 1 and not kw.get("dry_run"):
            wait = schedule.between_accounts(g["min"], g["max"]) + \
                schedule.rest_bonus(g["rest_chance"])
            out[-1]["wait_next"] = wait
            if not no_sleep:
                schedule.sleep_human(wait, 0, 0)
    return out


def describe_gates(driver_cls) -> list[tuple[str, str]]:
    c = driver_cls.caps if isinstance(driver_cls.caps, type(None)) else None
    return [(k, f"{v}{'' if driver_cls.caps.unattended() else ' (butuh manusia)'}")
            for k, v in GATES.items()]
