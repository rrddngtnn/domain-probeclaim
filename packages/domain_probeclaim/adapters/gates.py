"""Gate adapters: email, Turnstile (cfast), 2captcha HTTP, interactive manual, composite."""
from __future__ import annotations

import time
import requests

from ..core.httpses import sync_session_ua
from .base import AdapterResult, GateAdapter


class NoGate(GateAdapter):
    name = "passthrough"
    handles = "none"
    level = 2

    def run(self, ctx: dict) -> AdapterResult:
        return AdapterResult(ok=True, detail="no gate")


class BlockedGate(GateAdapter):
    name = "blocked"
    level = 0

    def __init__(self, handles: str = "unknown", reason: str = "no adapter configured"):
        self.handles = handles
        self.reason = reason

    def available(self) -> bool:
        return False

    def run(self, ctx: dict) -> AdapterResult:
        return AdapterResult(ok=False, detail=f"{self.handles}: {self.reason}")


class EmailGate(GateAdapter):
    """Mailbox verification adapter backed by MailboxBackend."""

    name = "email-poll"
    handles = "email"
    level = 2

    def __init__(self, mailbox=None, pattern: str | None = None,
                 timeout: float = 120.0, poll: float = 3.0):
        self.mailbox = mailbox
        self.pattern = pattern
        self.timeout = timeout
        self.poll = poll

    def available(self) -> bool:
        return self.mailbox is not None

    def run(self, ctx: dict) -> AdapterResult:
        ident = ctx.get("ident") or {}
        box = ident.get("mailbox")
        if box is None:
            box = self.mailbox.create(ctx["seed"])
            ident["email"] = box.address
            ident["email_token"] = box.token
            ident["mailbox"] = box
        pat = ctx.get("email_pattern") or self.pattern
        if not pat:
            return AdapterResult(ok=True, detail=f"mailbox={box.address}",
                                 data={"email": box.address, "email_token": box.token})
        hit, msg = self.mailbox.wait_for(
            box, pat, since=ctx.get("since"),
            timeout=self.timeout, poll=self.poll)
        if not hit:
            return AdapterResult(ok=False, detail=f"email timeout: {box.address}",
                                 retryable=True)
        return AdapterResult(
            ok=True, detail=f"matched:{str(hit)[:12]}",
            data={"email_code": hit, "email_message": msg},
        )


class TurnstileGate(GateAdapter):
    """Cloudflare Turnstile solver via HitamLegit6777/cfast (syncs session UA)."""

    name = "cfast-turnstile"
    handles = "turnstile"
    level = 2

    def __init__(self, client, bind_proxy: bool = True):
        self.client = client
        self.bind_proxy = bind_proxy

    def available(self) -> bool:
        return self.client is not None and (
            self.client.has_api() or self.client.has_bin())

    def run(self, ctx: dict) -> AdapterResult:
        url = ctx.get("captcha_url") or ctx.get("base_url") or ""
        sitekey = ctx.get("sitekey") or ""
        if not url or not sitekey:
            return AdapterResult(ok=True, detail="turnstile deferred (no sitekey yet)")

        proxy = ""
        if self.bind_proxy and ctx.get("route") is not None:
            proxy = ctx["route"].url() or ""

        res = self.client.solve_turnstile(
            url=url,
            sitekey=sitekey,
            action=ctx.get("captcha_action", ""),
            cdata=ctx.get("captcha_cdata", ""),
            proxy=proxy,
        )
        if not res.get("ok"):
            return AdapterResult(ok=False, detail=res.get("error", "turnstile_failed"),
                                 retryable=True)

        ua = res.get("ua") or ""
        if ua and ctx.get("session") is not None:
            sync_session_ua(ctx["session"], ua)

        return AdapterResult(
            ok=True,
            detail=f"turnstile solved ({res.get('elapsed', '?')}s)",
            data={"captcha_token": res["token"], "solver_ua": ua},
        )


class CaptchaHttpGate(GateAdapter):
    """Generic 2captcha-compatible solver (/in.php + /res.php) for reCAPTCHA/hCaptcha/Turnstile."""

    name = "2captcha-http"
    handles = "captcha"
    level = 2

    def __init__(self, api_url: str = "", api_key: str = "",
                 kind: str = "recaptcha_v2", poll_interval: float = 3.0,
                 timeout: float = 120.0):
        self.api_url = api_url.rstrip("/")
        self.api_key = api_key
        self.kind = kind
        self.poll_interval = poll_interval
        self.timeout = timeout

    def available(self) -> bool:
        return bool(self.api_url)

    def run(self, ctx: dict) -> AdapterResult:
        url = ctx.get("captcha_url") or ctx.get("base_url") or ""
        sitekey = ctx.get("sitekey") or ""
        if not url or not sitekey:
            return AdapterResult(ok=True, detail=f"{self.kind} deferred (no sitekey yet)")

        payload = {
            "key": self.api_key,
            "method": self._method_for(ctx.get("captcha_kind") or self.kind),
            "sitekey": sitekey,
            "googlekey": sitekey,
            "pageurl": url,
            "url": url,
            "json": 1,
        }
        if ctx.get("captcha_action"):
            payload["action"] = ctx["captcha_action"]

        r = requests.post(f"{self.api_url}/in.php", json=payload, timeout=20)
        j = r.json()
        if j.get("status") != 1:
            return AdapterResult(ok=False, detail=str(j.get("error") or j),
                                 retryable=True)

        tid = j["request"]
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            time.sleep(self.poll_interval)
            rr = requests.get(
                f"{self.api_url}/res.php",
                params={"key": self.api_key, "action": "get", "id": tid, "json": 1},
                timeout=20,
            )
            rj = rr.json()
            if rj.get("status") == 1:
                ua = rj.get("user_agent") or ""
                if ua and ctx.get("session") is not None:
                    sync_session_ua(ctx["session"], ua)
                return AdapterResult(
                    ok=True, detail=f"solved:{tid[:8]}",
                    data={"captcha_token": rj["request"], "solver_ua": ua},
                )
            err = str(rj.get("request") or rj.get("error") or "")
            if "NOT_READY" not in err:
                return AdapterResult(ok=False, detail=err or "captcha_error",
                                     retryable=True)
        return AdapterResult(ok=False, detail="captcha_timeout", retryable=True)

    @staticmethod
    def _method_for(kind: str) -> str:
        return {
            "recaptcha_v2": "userrecaptcha",
            "recaptcha_v3": "userrecaptcha",
            "hcaptcha": "hcaptcha",
            "turnstile": "turnstile",
        }.get(kind, "userrecaptcha")


class ManualGate(GateAdapter):
    """Human-in-the-loop / callback gate (3DS OTP, visual captcha, KYC, manual queue)."""

    name = "manual-callback"
    level = 1

    def __init__(self, handles: str = "captcha", on_challenge=None):
        self.handles = handles
        self.on_challenge = on_challenge

    def available(self) -> bool:
        return self.on_challenge is not None

    def run(self, ctx: dict) -> AdapterResult:
        if self.on_challenge is None:
            return AdapterResult(ok=False, detail=f"{self.handles}: missing callback")
        ans = self.on_challenge(ctx)
        if not ans:
            return AdapterResult(ok=False, detail=f"{self.handles}: aborted/empty")
        data = ans if isinstance(ans, dict) else {"challenge_response": ans}
        return AdapterResult(ok=True, detail=f"manual:{self.handles}", data=data)


class CompositeGate(GateAdapter):
    """Execute multiple gates in sequence (e.g. turnstile + email + manual_3ds)."""

    name = "composite"
    handles = "composite"

    def __init__(self, gates: list[GateAdapter]):
        self.gates = list(gates)

    @property
    def level(self) -> int:
        if not self.gates:
            return 2
        return min(g.level for g in self.gates)

    def available(self) -> bool:
        return all(g.available() for g in self.gates)

    def run(self, ctx: dict) -> AdapterResult:
        merged: dict = {}
        details = []
        for g in self.gates:
            res = g.run(ctx)
            if not res.ok:
                return AdapterResult(ok=False, detail=f"{g.name}: {res.detail}",
                                     retryable=res.retryable)
            if res.data:
                merged.update(res.data)
                ctx.update(res.data)
            details.append(f"{g.name}={res.detail}")
        return AdapterResult(ok=True, detail=" -> ".join(details), data=merged)
