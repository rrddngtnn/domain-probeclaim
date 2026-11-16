"""Claim strategies: promo-quota, direct target list, multi-TLD differ, read-only lookup."""
from __future__ import annotations

import hashlib
import random

from ..drivers.base import ClaimResult
from .base import ClaimStrategy


def pick_promo_fqdn(seed: str, default_tld: str = "example.test") -> str:
    rng = random.Random(hashlib.sha256(("fqdn" + seed).encode()).digest())
    words = ["project", "archive", "ledger", "studio", "workshop", "storage",
             "node", "stream", "core", "mesh", "frame", "corner"]
    return f"{rng.choice(words)}{rng.randint(1000, 99999)}.{default_tld}"


class PromoSlotClaim(ClaimStrategy):
    name = "promo-quota"
    level = 2

    def pick(self, driver, seed: str) -> list[str]:
        tld = getattr(driver, "default_tld", "example.test")
        return [pick_promo_fqdn(seed, tld)]

    def execute(self, driver, fqdn: str, ctx: dict | None = None) -> ClaimResult:
        return driver.claim(fqdn)


class DirectListClaim(ClaimStrategy):
    name = "direct-list"
    level = 2

    def __init__(self, targets: list[str] | None = None, stop_on_first: bool = True):
        self.targets = [t.strip() for t in (targets or []) if t and t.strip()]
        self.stop_on_first = stop_on_first

    def available(self) -> bool:
        return bool(self.targets)

    def pick(self, driver, seed: str) -> list[str]:
        return list(self.targets)

    def execute(self, driver, fqdn: str, ctx: dict | None = None) -> ClaimResult:
        return driver.claim(fqdn)


class TldDifferClaim(ClaimStrategy):
    """Probe multiple TLDs for the same root until one succeeds."""

    name = "tld-differ"
    level = 2

    def __init__(self, name_root: str = "", tlds: tuple[str, ...] = ("de", "com", "net")):
        self.name_root = name_root
        self.tlds = tuple(tlds)

    def pick(self, driver, seed: str) -> list[str]:
        root = self.name_root or f"node{hashlib.sha256(seed.encode()).hexdigest()[:6]}"
        return [f"{root}.{t}" for t in self.tlds]

    def execute(self, driver, fqdn: str, ctx: dict | None = None) -> ClaimResult:
        return driver.claim(fqdn)


class ReadOnlyProbeClaim(ClaimStrategy):
    """Read-only availability probe via driver.lookup() — never signs up or claims."""

    name = "readonly-lookup"
    level = 2

    def __init__(self, targets: list[str] | None = None):
        self.targets = list(targets or [])

    def pick(self, driver, seed: str) -> list[str]:
        if self.targets:
            return list(self.targets)
        tld = getattr(driver, "default_tld", "com")
        return [pick_promo_fqdn(seed, tld)]

    def execute(self, driver, fqdn: str, ctx: dict | None = None) -> ClaimResult:
        if not hasattr(driver, "lookup"):
            return ClaimResult(ok=False, fqdn=fqdn, error="driver_missing_lookup")
        res = driver.lookup(fqdn)
        taken = res.get("taken")
        return ClaimResult(
            ok=taken is False,
            fqdn=fqdn,
            status="available" if taken is False else ("taken" if taken is True else "error"),
            error=res.get("error"),
            raw=res,
        )
