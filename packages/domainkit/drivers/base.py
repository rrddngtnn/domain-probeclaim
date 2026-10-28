"""domainkit.drivers.base — antarmuka seragam untuk satu registrar.

Tujuan modul ini: kode di atasnya (CLI, runner, test) tidak pernah tahu
registrar mana yang dipakai, dan tidak pernah tahu apakah operasinya lewat
proxy. Dua abstraksi itu disuntikkan.

Driver hanya mendeklarasikan kemampuan dan cara bayar. Runner yang
memutuskan boleh atau tidak, berdasarkan `payment` dan `gate`.
"""
from __future__ import annotations

from dataclasses import dataclass, field


# Kategori pembayaran. Dipakai runner untuk memutuskan jalur mana yang
# dijalankan tanpa intervensi. "card" bukan larangan — itu penanda bahwa
# driver tidak bisa jalan unattended tanpa PSP sandbox.
PAYMENT_KINDS = ("none", "balance", "qris", "bank", "paypal", "voucher",
                 "crypto", "card", "unknown")

# Gerbang yang membuat otomasi penuh tidak mungkin.
GATES = {
    "none": "tidak ada gerbang",
    "email": "butuh verifikasi email",
    "kyc": "butuh dokumen identitas",
    "3ds": "butuh challenge 3DS dari issuer",
    "captcha": "butuh penyelesaian captcha",
    "manual_review": "order ditahan untuk review manual",
}


@dataclass
class ClaimResult:
    ok: bool
    fqdn: str = ""
    expires_at: str | None = None
    epp: str | None = None
    status: str | None = None
    error: str | None = None
    raw: dict = field(default_factory=dict)


@dataclass
class Capabilities:
    signup: bool = True
    contact: bool = True
    claim: bool = True
    list_domains: bool = True
    dns: bool = False
    renew: bool = False
    payment: str = "unknown"
    gate: str = "email"
    notes: str = ""

    def unattended(self) -> bool:
        """Bisa jalan tanpa manusia di tengah jalan?"""
        if self.payment == "card":
            return False
        return self.gate in ("none", "email")


class RegistrarDriver:
    """Kontrak. Turunan wajib mengisi `name` dan `caps`, lalu
    mengimplementasikan minimal signup/claim/list_domains."""

    name = "base"
    base_url = ""

    def __init__(self, route=None, session=None, mailbox=None, db=None,
                 dry_run=False):
        self.route = route            # netpool.Route: direct atau pool
        self.session = session        # sudah ber-fingerprint
        self.mailbox = mailbox
        self.db = db
        self.dry_run = dry_run

    # ---------- deklarasi ----------
    @property
    def caps(self) -> Capabilities:
        raise NotImplementedError

    @property
    def proxy_url(self):
        return self.route.url() if self.route else None

    def describe(self) -> dict:
        c = self.caps
        return {
            "name": self.name,
            "base_url": self.base_url,
            "payment": c.payment,
            "gate": c.gate,
            "gate_means": GATES.get(c.gate, "?"),
            "unattended": c.unattended(),
            "mode": self.route.mode if self.route else None,
            "exit_ip": self.route.exit_ip if self.route else None,
            "caps": {k: getattr(c, k) for k in
                     ("signup", "contact", "claim", "list_domains", "dns", "renew")},
        }

    # ---------- operasi ----------
    def signup(self, ident: dict) -> dict:
        raise NotImplementedError

    def save_contact(self, ident: dict) -> dict:
        raise NotImplementedError

    def claim(self, fqdn: str) -> ClaimResult:
        raise NotImplementedError

    def list_domains(self) -> list[dict]:
        raise NotImplementedError
