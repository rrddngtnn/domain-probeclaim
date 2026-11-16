"""Pluggable adapter contracts across all execution axes."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AdapterResult:
    ok: bool
    detail: str = ""
    data: dict | None = None
    retryable: bool = False


class Adapter:
    """Base adapter. level: 0=blocked, 1=assisted/interactive, 2=automated."""

    name = "base"
    level: int = 0

    def available(self) -> bool:
        return True

    def run(self, ctx: dict) -> AdapterResult:
        raise NotImplementedError


class IdentityAdapter(Adapter):
    """Builds or provides account + billing profile from a seed."""

    name = "identity"
    level = 2

    def build(self, seed: str, mailbox=None, email_domain: str = "example.test") -> dict:
        raise NotImplementedError

    def run(self, ctx: dict) -> AdapterResult:
        ident = self.build(
            ctx["seed"],
            mailbox=ctx.get("mailbox"),
            email_domain=ctx.get("email_domain", "example.test"),
        )
        return AdapterResult(ok=True, detail=ident.get("country", "ID"),
                             data={"ident": ident})


class TransportAdapter(Adapter):
    """Opens and prepares the HTTP session (TLS profile, UA, clearance cookies)."""

    name = "httpses"
    level = 2

    def open_session(self, seed: str, route=None, base_url: str = "",
                     ctx: dict | None = None):
        raise NotImplementedError


class GateAdapter(Adapter):
    """Solves one verification barrier (email, turnstile, recaptcha, 3ds, kyc)."""

    handles = "none"

    def run(self, ctx: dict) -> AdapterResult:
        raise NotImplementedError


class PaymentAdapter(Adapter):
    """Provides/executes payment method (none, voucher, sepa, card, balance)."""

    handles = "none"

    def run(self, ctx: dict) -> AdapterResult:
        raise NotImplementedError


class ClaimStrategy(Adapter):
    """Selects target domain(s) and executes claim/lookup workflow."""

    name = "promo"
    level = 2

    def pick(self, driver, seed: str) -> list[str]:
        raise NotImplementedError

    def execute(self, driver, fqdn: str, ctx: dict | None = None):
        raise NotImplementedError


@dataclass
class AdapterChain:
    identity: IdentityAdapter
    transport: TransportAdapter
    gate: GateAdapter
    payment: PaymentAdapter
    claim: ClaimStrategy
    blocked: list[Adapter] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.blocked

    @property
    def unattended(self) -> bool:
        if self.blocked:
            return False
        return min(
            self.identity.level,
            self.transport.level,
            self.gate.level,
            self.payment.level,
            self.claim.level,
        ) >= 2

    @property
    def assisted(self) -> bool:
        if self.blocked:
            return False
        return min(
            self.identity.level,
            self.transport.level,
            self.gate.level,
            self.payment.level,
            self.claim.level,
        ) >= 1
