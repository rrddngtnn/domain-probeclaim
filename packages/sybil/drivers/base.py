"""Base driver contract for target services."""
from __future__ import annotations

from dataclasses import dataclass, field

PAYMENT_KINDS = ("none", "balance", "qris", "bank", "paypal", "voucher",
                 "crypto", "card", "unknown")

GATES = {
    "none": "no verification barrier",
    "email": "requires email confirmation",
    "kyc": "requires identity documentation",
    "3ds": "requires 3DS issuer challenge",
    "captcha": "requires captcha solver",
    "manual_review": "order queued for manual inspection",
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
        if self.payment == "card":
            return False
        return self.gate in ("none", "email")


class RegistrarDriver:
    """Standard driver contract. Subclasses implement signup, claim, and list_domains."""

    name = "base"
    base_url = ""

    def __init__(self, route=None, session=None, mailbox=None, db=None,
                 dry_run=False):
        self.route = route
        self.session = session
        self.mailbox = mailbox
        self.db = db
        self.dry_run = dry_run

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

    def signup(self, ident: dict) -> dict:
        raise NotImplementedError

    def save_contact(self, ident: dict) -> dict:
        raise NotImplementedError

    def claim(self, fqdn: str) -> ClaimResult:
        raise NotImplementedError

    def list_domains(self) -> list[dict]:
        raise NotImplementedError
