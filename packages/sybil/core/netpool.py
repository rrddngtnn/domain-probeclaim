"""Sticky proxy allocation and direct network routing."""
from __future__ import annotations

import hashlib
import json
import os
import random
import time

try:
    import requests
except ImportError:
    requests = None

KIND_WEIGHT = {"mobile": 3.0, "residential": 2.0, "isp": 1.5, "datacenter": 0.4}
DEFAULT_BUDGET = {"pool": 3, "direct": 2}
DEFAULT_WINDOW_DAYS = 7


class ProxyPool:
    def __init__(self, path=None):
        self.path = path or os.path.join(os.getcwd(), "proxies.json")
        self.items = self._load(self.path)
        self.by_id = {self._id(p): p for p in self.items}
        self._health = {}

    @staticmethod
    def _load(path):
        if not os.path.exists(path):
            return []
        try:
            with open(path) as f:
                data = json.load(f)
        except (OSError, ValueError):
            return []
        if isinstance(data, dict):
            data = data.get("proxies", [])
        out = []
        for p in data:
            if isinstance(p, str):
                out.append({"url": p, "kind": "residential"})
            elif isinstance(p, dict) and p.get("url"):
                p.setdefault("kind", "residential")
                out.append(p)
        return out

    @staticmethod
    def _id(p):
        return hashlib.sha1(p["url"].encode()).hexdigest()[:12]

    def __len__(self):
        return len(self.by_id)

    def assign(self, seed):
        """Deterministic proxy assignment per identity seed."""
        if not self.by_id:
            return None
        pool = sorted(self.by_id.items())
        rng = random.Random(hashlib.sha256(seed.encode()).digest())
        weights = [KIND_WEIGHT.get(p["kind"], 1.0) for _, p in pool]
        return rng.choices([p for _, p in pool], weights=weights, k=1)[0]

    def check(self, proxy, timeout=10):
        """Verify egress IP or return None on failure."""
        if not proxy or requests is None:
            return None
        try:
            r = requests.get(
                "https://api.ipify.org",
                proxies={"http": proxy["url"], "https": proxy["url"]},
                timeout=timeout)
            ip = r.text.strip()
            ok = r.status_code == 200 and ip.count(".") == 3
            self._health[self._id(proxy)] = (time.time(), ip if ok else None)
            return ip if ok else None
        except Exception:
            self._health[self._id(proxy)] = (time.time(), None)
            return None

    def report(self, verbose=True):
        rows, alive = [], 0
        for pid, p in sorted(self.by_id.items()):
            ip = self.check(p)
            alive += bool(ip)
            rows.append((pid, p["kind"], ip))
            if verbose:
                print(f"  {pid}  {p['kind']:12} {'OK ' + ip if ip else 'DEAD'}")
        if verbose:
            print(f"\n  {alive}/{len(rows)} active")
        return alive, rows


class Route:
    """Network route decision for a single operation."""

    def __init__(self, mode, proxy, exit_ip, budget, window, error=None):
        self.mode = mode
        self.proxy = proxy
        self.exit_ip = exit_ip
        self.budget = budget
        self.window = window
        self.error = error

    @property
    def ok(self):
        return self.error is None

    def url(self):
        return self.proxy["url"] if self.proxy else None

    def __repr__(self):
        return (f"Route(mode={self.mode!r}, proxy={'set' if self.proxy else None}, "
                f"exit_ip={self.exit_ip!r}, budget={self.budget})")


def resolve_route(seed, pool=None, mode="auto", ip_checker=None,
                  budget=None, window=DEFAULT_WINDOW_DAYS):
    """Determine proxy vs direct routing."""
    budget = dict(DEFAULT_BUDGET, **(budget or {}))
    checker = ip_checker or current_ip

    if mode == "direct":
        return Route("direct", None, checker(), budget["direct"], window)

    pool = pool if pool is not None else ProxyPool()

    if mode == "pool" and not len(pool):
        return Route("pool", None, None, budget["pool"], window,
                     error="mode=pool but proxy pool is empty")

    if len(pool) and mode in ("auto", "pool"):
        proxy = pool.assign(seed)
        exit_ip = pool.check(proxy)
        if not exit_ip:
            target_url = proxy["url"] if proxy else "unknown"
            return Route("pool", proxy, None, budget["pool"], window,
                         error=f"proxy offline: {target_url[:48]}")
        return Route("pool", proxy, exit_ip, budget["pool"], window)

    return Route("direct", None, checker(), budget["direct"], window)


def current_ip(timeout=10):
    if requests is None:
        return None
    try:
        r = requests.get("https://api.ipify.org", timeout=timeout)
        ip = r.text.strip()
        return ip if r.status_code == 200 and ip.count(".") == 3 else None
    except Exception:
        return None
