"""mock_server.py — registrar tiruan berbasis FastAPI.

Meniru POLA, bukan vendor: validasi berurutan yang membalas error satu per
satu, kontak WHOIS wajib sebelum klaim, jatah per akun, 409 untuk nama
terpakai. Semua state di memori.

Jalankan:
    python -m domainkit.mock_server
    uvicorn domainkit.mock_server:app --port 8787

Endpoint:
    POST /api/auth/signup            {email,password[,name]}
    POST /api/auth/login             {email,password}
    GET  /api/auth/me
    POST /api/contacts               {contact:{...}, label}
    GET  /api/contacts
    GET  /api/domains/pricing
    POST /api/domains/register       {domain_name}
    GET  /api/domains
"""
from __future__ import annotations

import datetime
import itertools
import re

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

app = FastAPI(title="domainkit mock registrar", version="1.0.0")

FREE_PER_ACCOUNT = 2
SUPPORTED_TLDS = ("example.test", "test", "example")

# bentuk kontak: nama field -> pesan validasi
CONTACT_ORDER = ["first_name", "last_name", "email", "phone", "address1",
                 "city", "state", "postal_code"]

DB = {"users": {}, "sessions": {}, "contacts": {}, "domains": {}, "seq": itertools.count(1)}


def _uid():
    return next(DB["seq"])


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def _err(status, code, message=None):
    body = {"error": code}
    if message:
        body["message"] = message
    return JSONResponse(body, status_code=status)


def _user_from(request: Request):
    sid = request.cookies.get("dk_session")
    uid = DB["sessions"].get(sid)
    return DB["users"].get(uid) if uid else None


def _sld_ok(name: str) -> bool:
    return bool(re.fullmatch(r"[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?", name))


@app.get("/api/health")
def health():
    return {"ok": True, "ts": int(_now().timestamp() * 1000)}


@app.post("/api/auth/signup")
async def signup(request: Request, response: Response):
    body = await request.json()
    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""
    if not email or "@" not in email:
        return _err(400, "invalid_email")
    if len(password) < 8:
        return _err(400, "password_too_short", "Password minimal 8 karakter")
    if email in DB["users"]:
        return _err(409, "email_taken", "Email sudah terdaftar")
    uid = _uid()
    DB["users"][email] = {"id": uid, "email": email, "password": password,
                          "name": body.get("name"),
                          "email_verified": False, "free_used": 0}
    sid = f"s{uid}"
    DB["sessions"][sid] = email
    # JSONResponse langsung, bukan return dict: Response yang disuntikkan
    # di parameter tidak dipakai kalau handler membalas objek biasa.
    resp = JSONResponse({"user": {"id": uid, "email": email,
                                 "name": body.get("name")}}, status_code=201)
    resp.set_cookie("dk_session", sid, httponly=True, samesite="lax")
    return resp


@app.post("/api/auth/login")
async def login(request: Request, response: Response):
    body = await request.json()
    u = DB["users"].get((body.get("email") or "").lower())
    if not u or u["password"] != body.get("password"):
        return _err(400, "invalid_credentials", "Email atau password salah")
    sid = f"s{u['id']}"
    DB["sessions"][sid] = u["email"]
    resp = JSONResponse({"user": {"id": u["id"], "email": u["email"],
                                  "name": u["name"]}})
    resp.set_cookie("dk_session", sid, httponly=True, samesite="lax")
    return resp


@app.get("/api/auth/me")
def me(request: Request):
    u = _user_from(request)
    if not u:
        return _err(401, "unauthorized")
    return {"user": {"id": u["id"], "email": u["email"], "name": u["name"],
                     "email_verified": u["email_verified"],
                     "free_used": u["free_used"]}}


@app.post("/api/auth/verify")
async def verify(request: Request):
    body = await request.json()
    token = body.get("token")
    if not token:
        return _err(400, "token_kosong")
    u = _user_from(request)
    if not u:
        return _err(401, "unauthorized")
    u["email_verified"] = True
    return {"ok": True}


@app.post("/api/contacts")
async def save_contact(request: Request):
    u = _user_from(request)
    if not u:
        return _err(401, "unauthorized")
    body = await request.json()
    contact = body.get("contact")
    if not isinstance(contact, dict):
        return _err(400, "invalid_contact")
    # validasi berurutan: satu error per request, seperti server nyata
    for field in CONTACT_ORDER:
        if not contact.get(field):
            return _err(400, f"missing_{field}")
    if not body.get("label"):
        return _err(400, "missing_label")
    cid = _uid()
    contact.setdefault("country", "ID")
    DB["contacts"][u["email"]] = {"id": cid, "label": body["label"],
                                  "is_default": True, "contact": contact}
    return JSONResponse({"id": cid}, status_code=201)


@app.get("/api/contacts")
def list_contacts(request: Request):
    u = _user_from(request)
    if not u:
        return _err(401, "unauthorized")
    c = DB["contacts"].get(u["email"])
    return {"contacts": [c] if c else []}


@app.get("/api/domains/pricing")
def pricing():
    return {
        "pricing": [{"tld": t, "register_idr": 0, "renew_idr": 11500,
                     "transfer_idr": 50000, "free": True,
                     "promo": {"label": "mock hari pertama", "sampai": "2099-01-01"}}
                    for t in SUPPORTED_TLDS],
        "jatah_gratis": {"sisa": FREE_PER_ACCOUNT, "per_akun": FREE_PER_ACCOUNT,
                         "harga_lewat_idr": 100},
        "prelaunch_tlds": list(SUPPORTED_TLDS),
    }


@app.post("/api/domains/register")
async def register(request: Request):
    u = _user_from(request)
    if not u:
        return _err(401, "unauthorized")
    body = await request.json()
    fqdn = (body.get("domain_name") or "").strip().lower()
    if not fqdn or "." not in fqdn:
        return _err(400, "invalid_domain_name")
    sld, _, tld = fqdn.partition(".")
    if tld not in SUPPORTED_TLDS:
        return _err(403, "tld_not_available")
    if not _sld_ok(sld):
        return _err(400, "invalid_domain_name")
    if u["email"] not in DB["contacts"]:
        return _err(400, "missing_contact",
                    "Isi data pemilik domain dulu, lalu daftarkan lagi.")
    if u["free_used"] >= FREE_PER_ACCOUNT:
        return _err(402, "insufficient_balance")
    if fqdn in DB["domains"]:
        return _err(409, "domain_taken")
    u["free_used"] += 1
    exp = (_now() + datetime.timedelta(days=365)).strftime("%Y-%m-%d")
    rec = {"domain_name": fqdn, "status": "active", "expires_at": exp,
           "epp": f"E{_uid():06d}", "price_paid_idr": 0,
           "nameservers": ["ns1.mock.test", "ns2.mock.test"]}
    DB["domains"][fqdn] = rec
    return JSONResponse({
        "domain": {"domain_name": fqdn, "duration_years": 1,
                   "price_paid_idr": 0, "nameservers": rec["nameservers"]},
        "registry": {"code": 201, "data": {"status": "ACTIVE",
                                           "expiry_date": exp,
                                           "epp_code": rec["epp"]}},
    }, status_code=201)


@app.get("/api/domains")
def my_domains(request: Request):
    u = _user_from(request)
    if not u:
        return _err(401, "unauthorized")
    mine = [d for d in DB["domains"].values() if d["domain_name"].endswith(".test")
            or d["domain_name"].endswith(".example")]
    return {"domains": mine, "total": len(mine)}


def reset():
    """Untuk test: kosongkan semua state."""
    DB["users"].clear()
    DB["sessions"].clear()
    DB["contacts"].clear()
    DB["domains"].clear()
    DB["seq"] = itertools.count(1)


if __name__ == "__main__":
    import uvicorn
    # Mock server jalan tanpa TLS dan tanpa ALPN, jadi client yang mencoba
    # upgrade ke HTTP/2 (curl_cffi impersonate mengirim `Upgrade: h2c`)
    # membuat uvicorn kehilangan body dan app melihat request kosong.
    # http="h11" memaksa HTTP/1.1 polos: satu-satunya mode yang stabil
    # untuk server lokal pengembangan.
    uvicorn.run(app, host="127.0.0.1", port=8787,
                http="h11", ws="none", lifespan="off")
