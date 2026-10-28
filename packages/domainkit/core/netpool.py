"""domainkit.core.netpool — alokasi proxy sticky + fallback tanpa proxy.

Dua mode, satu antarmuka. Ini yang bikin driver di atasnya tidak pernah
tahu apakah operasinya lewat proxy atau langsung:

    mode="direct"  -> tidak ada proxy; exit_ip = IP publik mesin ini
    mode="pool"    -> proxy sticky, satu identitas = satu proxy selamanya

Aturan inti mode pool: rotasi IP di TENGAH umur satu akun yang bikin flag,
bukan rotasi antar akun. Karena itu assign() deterministik per seed,
bukan round-robin.

Tanpa proxy bukan mode "rusak". Ini mode yang sah: exit_ip tetap dicatat,
guard IP tetap jalan, cuma budget-nya jauh lebih kecil karena semua akun
keluar dari satu alamat.
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import time

try:
    import requests
except ImportError:                # pragma: no cover
    requests = None

# ASN datacenter = bendera merah di hampir semua layanan. Residensial/mobile
# yang berbobot. Kalau cuma punya datacenter, kecilkan batch drastis.
KIND_WEIGHT = {"mobile": 3.0, "residential": 2.0, "isp": 1.5, "datacenter": 0.4}

DEFAULT_BUDGET = {"pool": 3, "direct": 2}
DEFAULT_WINDOW_DAYS = 7


class ProxyPool:
    def __init__(self, path=None):
        self.path = path or os.path.join(os.getcwd(), "proxies.json")
        self.items = self._load(self.path)
        self.by_id = {self._id(p): p for p in self.items}
        self._health = {}

    # ---------- load ----------
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

    # ---------- allocation ----------
    def assign(self, seed):
        """Seed yang sama selalu dapat proxy yang sama. Weighted by kind."""
        if not self.by_id:
            return None
        pool = sorted(self.by_id.items())
        rng = random.Random(hashlib.sha256(seed.encode()).digest())
        weights = [KIND_WEIGHT.get(p["kind"], 1.0) for _, p in pool]
        return rng.choices([p for _, p in pool], weights=weights, k=1)[0]

    # ---------- health ----------
    def check(self, proxy, timeout=10):
        """Exit IP atau None kalau mati."""
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
            print(f"\n  {alive}/{len(rows)} hidup")
        return alive, rows


class Route:
    """Satu keputusan routing untuk satu operasi.

    Attribut:
      mode      "direct" | "pool"
      proxy     dict proxy atau None
      exit_ip   IP keluar yang terdeteksi (None kalau tidak bisa dicek)
      budget    berapa akun boleh dibuat per IP dalam window
      window    dalam hari
      error     alasan kalau routing gagal (proxy mati, dll)
    """

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
    """Tentukan routing. Ini satu-satunya tempat yang tahu soal proxy.

    mode:
      "auto"   -> pakai pool kalau ada isinya, kalau tidak direct
      "pool"   -> wajib proxy; gagal kalau pool kosong atau proxy mati
      "direct" -> tidak pernah pakai proxy, walau pool ada isinya

    Return Route. Route.error terisi kalau mode bisa dipenuhi.
    """
    budget = dict(DEFAULT_BUDGET, **(budget or {}))
    checker = ip_checker or current_ip

    if mode == "direct":
        return Route("direct", None, checker(), budget["direct"], window)

    pool = pool if pool is not None else ProxyPool()

    if mode == "pool" and not len(pool):
        return Route("pool", None, None, budget["pool"], window,
                     error="mode=pool tapi pool kosong")

    if len(pool) and mode in ("auto", "pool"):
        proxy = pool.assign(seed)
        exit_ip = pool.check(proxy)
        if not exit_ip:
            return Route("pool", proxy, None, budget["pool"], window,
                         error=f"proxy mati: {proxy['url'][:48]}")
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
