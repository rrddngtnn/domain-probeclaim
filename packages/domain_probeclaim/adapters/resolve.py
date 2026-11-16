"""Chain resolver: composes Identity, Transport, Gate, Payment, Claim from Capabilities."""
from __future__ import annotations

from dataclasses import dataclass, field

from . import claims, gates, identity, payments, transports
from .base import Adapter, AdapterChain
from .solvers.cfast import CfastClient


@dataclass
class ChainConfig:
    # Identity / SEPA
    locale: str | None = None
    static_profile: dict | None = None
    attach_sepa: bool | None = None
    sepa_country: str = "DE"
    sepa_override: dict | None = None

    # Transport / Solver (cfast + 2captcha-compatible)
    solver_url: str | None = None
    solver_key: str = ""
    cfast_bin: str | None = None
    cfast_profile: str | None = None
    use_cfast_clearance: bool = False
    clearance_url: str = ""
    impersonate: str | None = None
    user_agent_override: str | None = None

    # Gates
    gate_override: str | None = None
    captcha_kind: str | None = None
    email_pattern: str | None = None
    on_challenge: object = None
    bind_solver_proxy: bool = True

    # Payments
    payment_override: str | None = None
    vouchers: list[str] = field(default_factory=list)
    voucher_generator: object = None
    voucher_reusable: bool = False
    cards: list[dict] = field(default_factory=list)
    card_provider: object = None
    on_3ds: object = None
    validate_card_luhn: bool = True
    balance_checker: object = None

    # Claim
    claim_mode: str = "auto"
    targets: list[str] = field(default_factory=list)
    tlds: tuple[str, ...] = ("de", "com", "net")
    name_root: str = ""

    # Policy
    allow_assisted: bool = True


def _build_cfast(cfg: ChainConfig) -> CfastClient | None:
    if not (cfg.solver_url or cfg.cfast_bin):
        return None
    return CfastClient(
        api_url=cfg.solver_url,
        bin_path=cfg.cfast_bin,
        profile_path=cfg.cfast_profile,
    )


def _resolve_gate(caps, mailbox, cfg: ChainConfig, cfast: CfastClient | None):
    gate_name = cfg.gate_override or getattr(caps, "gate", "none")
    ckind = cfg.captcha_kind or getattr(caps, "captcha_kind", None) or "recaptcha_v2"

    if gate_name == "none":
        return gates.NoGate()

    if gate_name == "email":
        if mailbox is not None:
            return gates.EmailGate(mailbox=mailbox, pattern=cfg.email_pattern)
        return gates.BlockedGate("email", "mailbox backend not wired")

    if gate_name in ("turnstile", "captcha"):
        if (gate_name == "turnstile" or ckind == "turnstile") and cfast is not None:
            g = gates.TurnstileGate(cfast, bind_proxy=cfg.bind_solver_proxy)
            if g.available():
                return g
        if cfg.solver_url:
            return gates.CaptchaHttpGate(
                api_url=cfg.solver_url, api_key=cfg.solver_key, kind=ckind)
        if cfg.on_challenge is not None:
            return gates.ManualGate(handles=gate_name, on_challenge=cfg.on_challenge)
        return gates.BlockedGate(gate_name, "missing solver_url / cfast / on_challenge")

    if gate_name in ("3ds", "kyc", "manual_review"):
        if cfg.on_challenge is not None:
            return gates.ManualGate(handles=gate_name, on_challenge=cfg.on_challenge)
        return gates.BlockedGate(gate_name, "interactive on_challenge callback required")

    return gates.BlockedGate(gate_name, f"unsupported gate {gate_name!r}")


def _resolve_payment(caps, cfg: ChainConfig):
    pay_name = cfg.payment_override or getattr(caps, "payment", "none")

    if pay_name in ("none", "unknown"):
        return payments.NoPayment()

    if pay_name == "voucher":
        v = payments.VoucherPayment(
            codes=cfg.vouchers, generator=cfg.voucher_generator,
            reusable=cfg.voucher_reusable)
        return v if v.available() else payments.BlockedPayment(
            "voucher", "vouchers pool/generator empty")

    if pay_name in ("sepa", "bank"):
        s = payments.SepaPayment(country=cfg.sepa_country, override=cfg.sepa_override)
        return s if s.available() else payments.BlockedPayment(
            "sepa", "override IBAN failed mod-97")

    if pay_name == "card":
        c = payments.CardPayment(
            cards=cfg.cards, provider=cfg.card_provider,
            on_3ds=cfg.on_3ds, validate_luhn=cfg.validate_card_luhn)
        return c if c.available() else payments.BlockedPayment(
            "card", "cards pool / provider missing")

    if pay_name == "balance":
        b = payments.BalancePayment(checker=cfg.balance_checker)
        return b if b.available() else payments.BlockedPayment(
            "balance", "balance_checker missing")

    if cfg.on_challenge is not None:
        return payments.BalancePayment(checker=cfg.on_challenge)
    return payments.BlockedPayment(pay_name, f"no payment adapter for {pay_name!r}")


def _resolve_claim(caps, cfg: ChainConfig):
    mode = cfg.claim_mode
    if mode == "auto":
        mode = "readonly" if not getattr(caps, "claim", True) else (
            "direct" if cfg.targets else "promo")

    if mode == "readonly":
        return claims.ReadOnlyProbeClaim(targets=cfg.targets)
    if mode == "direct":
        return claims.DirectListClaim(targets=cfg.targets)
    if mode == "differ":
        return claims.TldDifferClaim(name_root=cfg.name_root, tlds=cfg.tlds)
    return claims.PromoSlotClaim()


def build_chain(caps, *, mailbox=None, config: ChainConfig | None = None) -> AdapterChain:
    """Assemble full AdapterChain from target Capabilities and runtime ChainConfig."""
    cfg = config or ChainConfig()
    cfast = _build_cfast(cfg)

    loc = cfg.locale or getattr(caps, "locale", "id")
    pay_kind = cfg.payment_override or getattr(caps, "payment", "none")
    attach_sepa = cfg.attach_sepa if cfg.attach_sepa is not None else (
        pay_kind in ("sepa", "bank") or cfg.sepa_override is not None
    )
    if cfg.static_profile is not None:
        ident_ad = identity.StaticIdentityAdapter(cfg.static_profile)
    else:
        ident_ad = identity.LocaleIdentityAdapter(
            locale=loc, attach_sepa=attach_sepa, sepa_country=cfg.sepa_country)

    if cfg.use_cfast_clearance and cfast is not None:
        trans_ad = transports.CfastClearanceTransport(
            cfast, target_url=cfg.clearance_url,
            impersonate=cfg.impersonate or "safari18_0")
    else:
        trans_ad = transports.HttpSesTransport(
            impersonate=cfg.impersonate or "chrome131",
            user_agent_override=cfg.user_agent_override)

    gate_ad = _resolve_gate(caps, mailbox, cfg, cfast)
    pay_ad = _resolve_payment(caps, cfg)
    claim_ad = _resolve_claim(caps, cfg)

    min_lvl = 1 if cfg.allow_assisted else 2
    candidates: tuple[Adapter, ...] = (ident_ad, trans_ad, gate_ad, pay_ad, claim_ad)
    blocked: list[Adapter] = [
        a for a in candidates
        if not a.available() or a.level < min_lvl
    ]
    return AdapterChain(
        identity=ident_ad,
        transport=trans_ad,
        gate=gate_ad,
        payment=pay_ad,
        claim=claim_ad,
        blocked=blocked,
    )


def explain_chain(chain: AdapterChain) -> str:
    rows = [
        f"identity  : {chain.identity.name:<18} lvl={chain.identity.level} avail={chain.identity.available()}",
        f"transport : {chain.transport.name:<18} lvl={chain.transport.level} avail={chain.transport.available()}",
        f"gate      : {chain.gate.name:<18} lvl={chain.gate.level} avail={chain.gate.available()} ({chain.gate.handles})",
        f"payment   : {chain.payment.name:<18} lvl={chain.payment.level} avail={chain.payment.available()} ({chain.payment.handles})",
        f"claim     : {chain.claim.name:<18} lvl={chain.claim.level} avail={chain.claim.available()}",
        f"ready     : {'YES' if chain.ok else 'BLOCKED -> ' + ', '.join(a.name + '(' + getattr(a, 'handles', a.name) + ')' for a in chain.blocked)}",
        f"auto      : {'FULL' if chain.unattended else ('ASSISTED' if chain.assisted else 'NO')}",
    ]
    return "\n".join(rows)
