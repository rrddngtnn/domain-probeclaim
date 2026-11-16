"""Flexible payment adapters: none, balance, voucher, SEPA (with generator), card."""
from __future__ import annotations

from ..core.sepa import generate_sepa_profile, validate_iban
from .base import AdapterResult, PaymentAdapter


def luhn_valid(pan: str) -> bool:
    digits = [int(c) for c in "".join(pan.split()) if c.isdigit()]
    if len(digits) < 12:
        return False
    total = 0
    for idx, d in enumerate(reversed(digits)):
        if idx % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


class NoPayment(PaymentAdapter):
    name = "free"
    handles = "none"
    level = 2

    def run(self, ctx: dict) -> AdapterResult:
        return AdapterResult(ok=True, detail="no payment required",
                             data={"payment": {"kind": "none"}})


class BlockedPayment(PaymentAdapter):
    name = "blocked"
    level = 0

    def __init__(self, handles: str = "unknown", reason: str = "no handler wired"):
        self.handles = handles
        self.reason = reason

    def available(self) -> bool:
        return False

    def run(self, ctx: dict) -> AdapterResult:
        return AdapterResult(ok=False, detail=f"{self.handles}: {self.reason}")


class BalancePayment(PaymentAdapter):
    name = "prepaid-balance"
    handles = "balance"
    level = 2

    def __init__(self, checker=None):
        self.checker = checker

    def available(self) -> bool:
        return self.checker is not None

    def run(self, ctx: dict) -> AdapterResult:
        if self.checker is None:
            return AdapterResult(ok=False, detail="balance checker missing")
        res = self.checker(ctx)
        if isinstance(res, AdapterResult):
            return res
        ok = bool(res)
        return AdapterResult(ok=ok, detail="balance ok" if ok else "insufficient balance",
                             data={"payment": {"kind": "balance", "raw": res}})


class VoucherPayment(PaymentAdapter):
    """Promo / voucher pool with deterministic or sequential rotation."""

    name = "voucher-pool"
    handles = "voucher"
    level = 2

    def __init__(self, codes: list[str] | None = None, generator=None,
                 reusable: bool = False):
        self.codes = [c.strip() for c in (codes or []) if c and c.strip()]
        self.generator = generator
        self.reusable = reusable
        self._idx = 0

    def available(self) -> bool:
        return bool(self.codes) or self.generator is not None

    def next_code(self, ctx: dict) -> str | None:
        if self.codes:
            if self.reusable:
                code = self.codes[self._idx % len(self.codes)]
                self._idx += 1
                return code
            return self.codes.pop(0)
        if self.generator is not None:
            return self.generator(ctx)
        return None

    def run(self, ctx: dict) -> AdapterResult:
        code = self.next_code(ctx)
        if not code:
            return AdapterResult(ok=False, detail="voucher pool exhausted")
        pay = {"kind": "voucher", "code": code}
        return AdapterResult(ok=True, detail=f"voucher={code[:4]}***",
                             data={"payment": pay, "voucher": code})


class SepaPayment(PaymentAdapter):
    """SEPA Direct Debit: uses caller override or generates MOD-97 valid IBAN/BIC/mandate."""

    name = "sepa-direct-debit"
    handles = "sepa"
    level = 2

    def __init__(self, country: str = "DE", override: dict | None = None):
        self.country = country
        self.override = dict(override) if override else None

    def available(self) -> bool:
        if self.override:
            return bool(self.override.get("iban")) and validate_iban(self.override["iban"])
        return True

    def run(self, ctx: dict) -> AdapterResult:
        ident = ctx.get("ident") or {}
        if self.override:
            sepa = dict(self.override)
            if not validate_iban(sepa.get("iban", "")):
                return AdapterResult(ok=False, detail="override IBAN failed mod-97")
            sepa.setdefault("account_holder", ident.get("nama", ""))
        else:
            sepa = ident.get("sepa") or generate_sepa_profile(
                ctx["seed"], holder=ident.get("nama", ""), country=self.country)
        pay = {"kind": "sepa", **sepa}
        return AdapterResult(
            ok=True,
            detail=f"{sepa['country']} {sepa['iban'][:8]}..{sepa['iban'][-4:]}",
            data={"payment": pay, "sepa": sepa},
        )


class CardPayment(PaymentAdapter):
    """Flexible card payment adapter: accepts card pool or issuer callable + optional 3DS hook."""

    name = "card-flexible"
    handles = "card"

    def __init__(self, cards: list[dict] | None = None,
                 provider=None, on_3ds=None, validate_luhn: bool = True):
        self.cards = [dict(c) for c in (cards or [])]
        self.provider = provider
        self.on_3ds = on_3ds
        self.validate_luhn = validate_luhn

    @property
    def level(self) -> int:
        if not self.available():
            return 0
        if self.on_3ds is not None:
            return 1
        return 2 if self.provider is not None else 1

    def available(self) -> bool:
        return bool(self.cards) or self.provider is not None

    def run(self, ctx: dict) -> AdapterResult:
        card = None
        if self.provider is not None:
            card = self.provider(ctx)
        elif self.cards:
            card = self.cards.pop(0)
        if not card:
            return AdapterResult(ok=False, detail="no card available")

        pan = str(card.get("number") or card.get("pan") or "")
        if self.validate_luhn and pan and not luhn_valid(pan):
            return AdapterResult(ok=False, detail="card failed luhn check")

        pay = {"kind": "card", **card}
        if self.on_3ds is not None:
            ctx["pending_card"] = pay
            challenge = self.on_3ds(ctx)
            if not challenge:
                return AdapterResult(ok=False, detail="3DS aborted/failed")
            pay["three_ds"] = challenge

        masked = f"****{pan[-4:]}" if len(pan) >= 4 else "card"
        return AdapterResult(ok=True, detail=masked, data={"payment": pay})
