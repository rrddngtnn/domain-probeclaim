"""Identity adapters (multi-locale synthetic profiles + optional SEPA + static)."""
from __future__ import annotations

from ..core.identity import make_identity
from ..core.sepa import generate_sepa_profile
from .base import IdentityAdapter


class LocaleIdentityAdapter(IdentityAdapter):
    name = "locale-identity"
    level = 2

    def __init__(self, locale: str = "id", attach_sepa: bool = False,
                 sepa_country: str = "DE"):
        self.locale = locale
        self.attach_sepa = attach_sepa
        self.sepa_country = sepa_country

    def build(self, seed: str, mailbox=None, email_domain: str = "example.test") -> dict:
        ident = make_identity(seed, email_domain=email_domain, locale=self.locale)
        if mailbox is not None:
            box = mailbox.create(seed)
            ident["email"] = box.address
            ident["email_token"] = box.token
            ident["mailbox"] = box
        if self.attach_sepa:
            ident["sepa"] = generate_sepa_profile(
                seed, holder=ident["nama"], country=self.sepa_country)
        return ident


class StaticIdentityAdapter(IdentityAdapter):
    """Use a caller-supplied identity dict (e.g. legitimate owned billing profile)."""

    name = "static-identity"
    level = 2

    def __init__(self, profile: dict):
        self.profile = dict(profile)

    def available(self) -> bool:
        return bool(self.profile.get("email"))

    def build(self, seed: str, mailbox=None, email_domain: str = "example.test") -> dict:
        out = dict(self.profile)
        out.setdefault("seed", seed)
        return out
