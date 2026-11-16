"""Read-only RDAP availability driver (no signup, no account mutation)."""
from __future__ import annotations

from .base import Capabilities, ClaimResult, RegistrarDriver


class RdapDriver(RegistrarDriver):
    name = "rdap"
    base_url = "https://rdap.org"
    default_tld = "com"

    @property
    def caps(self) -> Capabilities:
        return Capabilities(
            signup=False,
            contact=False,
            claim=False,
            list_domains=False,
            payment="none",
            gate="none",
            notes="read-only ICANN RDAP availability probe",
        )

    def lookup(self, fqdn: str) -> dict:
        if self.session is None:
            raise RuntimeError("Driver requires active session")
        url = f"{self.base_url}/domain/{fqdn}"
        try:
            r = self.session.get(url, timeout=20)
        except Exception:
            r = None
        if r is None or r.status_code == 403:
            import requests
            proxies = getattr(self.session, "proxies", None) or None
            r = requests.get(
                url,
                headers={"Accept": "application/rdap+json, application/json"},
                proxies=proxies,
                timeout=20,
            )
        if r.status_code == 200:
            try:
                raw = r.json()
            except ValueError:
                raw = {}
            return {"fqdn": fqdn, "taken": True, "status": 200, "raw": raw}
        if r.status_code == 404:
            return {"fqdn": fqdn, "taken": False, "status": 404, "raw": None}
        return {"fqdn": fqdn, "taken": None, "status": r.status_code,
                "error": f"http_{r.status_code}", "raw": None}

    def signup(self, ident: dict) -> dict:
        raise NotImplementedError("RdapDriver is read-only")

    def save_contact(self, ident: dict) -> dict:
        raise NotImplementedError("RdapDriver is read-only")

    def claim(self, fqdn: str) -> ClaimResult:
        res = self.lookup(fqdn)
        if res["taken"] is False:
            return ClaimResult(ok=True, fqdn=fqdn, status="available", raw=res)
        return ClaimResult(
            ok=False, fqdn=fqdn,
            status="taken" if res["taken"] else "error",
            error=res.get("error") or "already_registered",
            raw=res,
        )

    def list_domains(self) -> list[dict]:
        return []
