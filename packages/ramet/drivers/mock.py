"""ramet.drivers.mock — driver contoh yang bicara ke mock server lokal.

Ini bukan tiruan registrar tertentu. Ini tiruan POLA: signup -> kontak ->
klaim, dengan validasi berurutan yang mengembalikan error satu per satu.
Tujuannya dua:

  1. test suite bisa jalan tanpa jaringan sama sekali
  2. jadi referensi bentuk driver untuk registrar sungguhan

Mock server-nya ada di `mock_server.py` (FastAPI). Driver ini juga bisa
dipakai dengan base_url apa pun yang mengikuti kontrak yang sama.
"""
from __future__ import annotations

import json

from ..core.httpses import post_json
from .base import Capabilities, ClaimResult, RegistrarDriver


class MockDriver(RegistrarDriver):
    name = "mock"
    base_url = "http://127.0.0.1:8787"

    def __init__(self, base_url=None, **kw):
        super().__init__(**kw)
        if base_url:
            self.base_url = base_url.rstrip("/")

    @property
    def caps(self) -> Capabilities:
        return Capabilities(
            dns=True, renew=True,
            payment="none", gate="email",
            notes="mock server lokal; kontrak sama dengan registrar nyata",
        )

    # ---------- helpers ----------
    def _url(self, path: str) -> str:
        return self.base_url + path

    def _s(self):
        if self.session is None:
            raise RuntimeError("driver butuh session dari httpses.session_for")
        return self.session

    # ---------- operasi ----------
    def signup(self, ident: dict) -> dict:
        if self.dry_run:
            return {"dry_run": True, "email": ident["email"]}
        r = post_json(self._s(), self._url("/api/auth/signup"), {
            "email": ident["email"],
            "password": ident["password"],
            "name": ident["nama"],
        })
        if r.status_code >= 400:
            raise RuntimeError(f"signup {r.status_code} {r.text[:160]}")
        return r.json()

    def save_contact(self, ident: dict) -> dict:
        if self.dry_run:
            return {"dry_run": True}
        payload = {
            "contact": {
                "first_name": ident["first_name"],
                "last_name": ident["last_name"],
                "email": ident["email"],
                "phone": ident["telepon"],
                "address1": ident["alamat"],
                "city": ident["kota"],
                "state": ident["provinsi"],
                "postal_code": ident["kodepos"],
            },
            "label": "Utama",
        }
        r = post_json(self._s(), self._url("/api/contacts"), payload)
        if r.status_code >= 400:
            raise RuntimeError(f"contact {r.status_code} {r.text[:160]}")
        return r.json()

    def claim(self, fqdn: str) -> ClaimResult:
        if self.dry_run:
            return ClaimResult(ok=False, fqdn=fqdn,
                               error="dry_run", raw={"dry_run": True})
        r = post_json(self._s(), self._url("/api/domains/register"),
                      {"domain_name": fqdn})
        try:
            body = r.json()
        except ValueError:
            body = {"raw": r.text[:200]}
        if r.status_code >= 400:
            return ClaimResult(ok=False, fqdn=fqdn,
                               error=body.get("error") or r.text[:80],
                               raw=body)
        dn = body.get("registry", {}).get("data", {}) if isinstance(body, dict) else {}
        return ClaimResult(
            ok=True, fqdn=fqdn,
            expires_at=dn.get("expiry_date"),
            epp=dn.get("epp_code"),
            status=dn.get("status"),
            raw=body,
        )

    def list_domains(self) -> list[dict]:
        r = self._s().get(self._url("/api/domains"), timeout=20)
        r.raise_for_status()
        return r.json().get("domains", [])
