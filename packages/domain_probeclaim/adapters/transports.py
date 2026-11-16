"""Transport adapters (standard httpses + cfast managed-challenge clearance)."""
from __future__ import annotations

from ..core.httpses import IMPERSONATE, session_for, sync_session_ua
from .base import AdapterResult, TransportAdapter


class HttpSesTransport(TransportAdapter):
    name = "httpses"
    level = 2

    def __init__(self, impersonate: str = IMPERSONATE,
                 user_agent_override: str | None = None):
        self.impersonate = impersonate
        self.user_agent_override = user_agent_override

    def open_session(self, seed: str, route=None, base_url: str = "",
                     ctx: dict | None = None):
        http_ver = "v1" if (base_url or "").startswith("http://") else None
        proxy = route.proxy if route else None
        return session_for(
            seed, proxy,
            impersonate=self.impersonate,
            http_version=http_ver,
            user_agent_override=self.user_agent_override,
        )

    def run(self, ctx: dict) -> AdapterResult:
        sess, ua = self.open_session(
            ctx["seed"], route=ctx.get("route"),
            base_url=ctx.get("base_url", ""), ctx=ctx)
        return AdapterResult(ok=True, detail=ua[:48],
                             data={"session": sess, "ua": ua})


class CfastClearanceTransport(TransportAdapter):
    """Solves Cloudflare managed challenge (`cf_clearance`) before opening session."""

    name = "cfast-clearance"
    level = 2

    def __init__(self, client, target_url: str = "",
                 impersonate: str = "safari18_0"):
        self.client = client
        self.target_url = target_url
        self.impersonate = impersonate

    def available(self) -> bool:
        return self.client is not None and self.client.has_bin()

    def open_session(self, seed: str, route=None, base_url: str = "",
                     ctx: dict | None = None):
        url = self.target_url or base_url
        proxy_url = route.url() if route else ""
        res = self.client.solve_managed_challenge(url, proxy=proxy_url or "")
        ua = res.get("ua") or None
        http_ver = "v1" if (base_url or "").startswith("http://") else None
        proxy = route.proxy if route else None
        sess, final_ua = session_for(
            seed, proxy,
            impersonate=self.impersonate,
            http_version=http_ver,
            user_agent_override=ua,
        )
        if res.get("ok") and res.get("cf_clearance"):
            sync_session_ua(sess, final_ua)
            cookies = getattr(sess, "cookies", None)
            if cookies is not None:
                cookies.set("cf_clearance", res["cf_clearance"],
                            domain=res.get("domain") or None)
        if ctx is not None:
            ctx["clearance_result"] = res
        return sess, final_ua

    def run(self, ctx: dict) -> AdapterResult:
        sess, ua = self.open_session(
            ctx["seed"], route=ctx.get("route"),
            base_url=ctx.get("base_url", ""), ctx=ctx)
        res = ctx.get("clearance_result") or {}
        if not res.get("ok"):
            return AdapterResult(ok=False, detail=res.get("error", "clearance_failed"))
        return AdapterResult(ok=True, detail="cf_clearance",
                             data={"session": sess, "ua": ua,
                                   "cf_clearance": res["cf_clearance"]})
