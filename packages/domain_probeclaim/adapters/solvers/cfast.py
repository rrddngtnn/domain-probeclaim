"""Client for HitamLegit6777/cfast (Turnstile API + cf_clearance binary)."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from urllib.parse import urlparse

import requests


def _read_profile_ua(profile_path: str | None) -> str:
    if not profile_path or not os.path.isfile(profile_path):
        return ""
    try:
        with open(profile_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        headers = ((data.get("transport") or {}).get("headers") or {})
        for k, v in headers.items():
            if k.lower() == "user-agent":
                return str(v)
    except Exception:
        pass
    return ""


DEFAULT_CFAST_DIR = "/home/azuramaru/tools/cfast"


def _default_bin() -> str | None:
    env = os.environ.get("TS_BIN")
    if env:
        return env
    cand = os.path.join(DEFAULT_CFAST_DIR, "challenge")
    return cand if os.path.isfile(cand) else None


def _default_profile() -> str | None:
    env = os.environ.get("TS_PROFILE")
    if env:
        return env
    cand = os.path.join(DEFAULT_CFAST_DIR, "profile_fast.json")
    return cand if os.path.isfile(cand) else None


class CfastClient:
    """Talks to cfast's solver_api.py (:8810) and/or native `challenge` binary."""

    def __init__(self, api_url: str | None = "http://127.0.0.1:8810",
                 bin_path: str | None = None,
                 profile_path: str | None = None,
                 timeout: float = 120.0):
        self.api_url = api_url.rstrip("/") if api_url else None
        self.bin_path = bin_path or _default_bin()
        self.profile_path = profile_path or _default_profile()
        self.timeout = timeout

    def has_api(self) -> bool:
        return bool(self.api_url)

    def has_bin(self) -> bool:
        return bool(self.bin_path and os.path.isfile(self.bin_path)
                    and self.profile_path and os.path.isfile(self.profile_path))

    def health(self) -> dict | None:
        if not self.api_url:
            return None
        try:
            r = requests.get(f"{self.api_url}/health", timeout=5)
            return r.json() if r.status_code == 200 else None
        except Exception:
            return None

    def solve_turnstile(self, url: str, sitekey: str, action: str = "",
                        cdata: str = "", proxy: str = "") -> dict:
        """Solve Turnstile via cfast HTTP /solve (preferred) or direct binary."""
        if self.api_url:
            payload = {
                "url": url,
                "sitekey": sitekey,
                "action": action,
                "cdata": cdata,
                "proxy": proxy,
                "timeout": self.timeout,
            }
            r = requests.post(f"{self.api_url}/solve", json=payload,
                              timeout=self.timeout + 10)
            body = r.json()
            if body.get("status") == 1 and body.get("token"):
                return {
                    "ok": True,
                    "token": body["token"],
                    "ua": body.get("ua") or "",
                    "elapsed": body.get("elapsed"),
                }
            return {"ok": False, "error": body.get("error") or "cfast_solve_failed"}

        if not self.has_bin():
            return {"ok": False, "error": "cfast_unconfigured"}

        return self._run_challenge_bin(
            url=url, sitekey=sitekey, action=action, cdata=cdata, proxy=proxy)

    def solve_managed_challenge(self, url: str, proxy: str = "") -> dict:
        """Solve Cloudflare managed challenge via ./challenge -> cf_clearance cookie."""
        if not self.has_bin():
            return {"ok": False, "error": "cfast_bin_or_profile_missing"}
        return self._run_challenge_bin(url=url, proxy=proxy, managed=True)

    def _run_challenge_bin(self, url: str, sitekey: str = "", action: str = "",
                           cdata: str = "", proxy: str = "",
                           managed: bool = False) -> dict:
        workdir = tempfile.mkdtemp(prefix="cfast-")
        target = os.path.join(workdir, "run")
        cmd = [
            self.bin_path, "--page", url, target,
            "--solve", "--fingerprint", self.profile_path,
        ]
        if not managed:
            cmd += ["--sitekey", sitekey, "--blank-page"]
            if action:
                cmd += ["--action", action]
            if cdata:
                cmd += ["--cdata", cdata]
        if proxy:
            px = proxy if "://" in proxy else f"http://{proxy}"
            cmd += ["--proxy", px]

        try:
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  timeout=self.timeout)
        except subprocess.TimeoutExpired:
            shutil.rmtree(workdir, ignore_errors=True)
            return {"ok": False, "error": "cfast_timeout"}

        lines = [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]
        shutil.rmtree(workdir, ignore_errors=True)
        ua = _read_profile_ua(self.profile_path)

        if managed:
            for ln in reversed(lines):
                if ln.startswith("cf_clearance="):
                    val = ln.split("=", 1)[1].strip()
                    return {
                        "ok": True,
                        "cf_clearance": val,
                        "domain": urlparse(url).hostname or "",
                        "ua": ua,
                    }
        else:
            for ln in reversed(lines):
                if ln.startswith(".") or (ln.startswith("1.") and len(ln) > 100):
                    return {"ok": True, "token": ln, "ua": ua}

        err_src = (proc.stderr or proc.stdout or "cfast_failed").strip().splitlines()
        return {"ok": False, "error": (err_src[-1] if err_src else "cfast_failed")[:200]}
