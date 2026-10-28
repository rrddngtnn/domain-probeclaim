"""HTTP sessions with TLS and browser impersonation profiles."""
from __future__ import annotations

import json
import random

try:
    from curl_cffi import requests as cf_requests
    HAS_CFFI = True
except ImportError:
    cf_requests = None
    HAS_CFFI = False

import requests

IMPERSONATE = "chrome131"

UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
]

BASE_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Sec-Ch-Ua": '"Chromium";v="131", "Not_A Brand";v="24"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-User": "?1",
    "Sec-Fetch-Dest": "document",
    "Upgrade-Insecure-Requests": "1",
    "DNT": "1",
}


def user_agent(seed: str) -> str:
    return random.Random(seed).choice(UA_POOL)


def session_for(seed: str, proxy=None, impersonate=IMPERSONATE,
                http_version=None):
    """Create configured session with user agent and optional proxy."""
    ua = user_agent(seed)
    headers = dict(BASE_HEADERS, **{"User-Agent": ua})
    px = proxy["url"] if proxy else None
    proxies = {"http": px, "https": px} if px else None

    if HAS_CFFI:
        kw = {"impersonate": impersonate, "proxies": proxies}
        if http_version:
            kw["http_version"] = http_version
        s = cf_requests.Session(**kw)
        s.headers.update(headers)
        return s, ua

    s = requests.Session()
    if proxies:
        s.proxies = proxies
    s.headers.update(headers)
    from requests.adapters import HTTPAdapter
    a = HTTPAdapter(pool_connections=4, pool_maxsize=8)
    s.mount("https://", a)
    s.mount("http://", a)
    return s, ua


def get_json(s, url, **kw):
    r = s.get(url, timeout=kw.pop("timeout", 25), **kw)
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, r.text


def post_json(s, url, payload, headers=None, timeout=25):
    """Serialize payload explicitly to maintain consistent behavior across engines."""
    h = {"Content-Type": "application/json",
         "Accept": "application/json, text/plain, */*"}
    if headers:
        h.update(headers)
    body = json.dumps(payload) if not isinstance(payload, (str, bytes)) else payload
    return s.post(url, data=body, headers=h, timeout=timeout,
                  allow_redirects=True)


def fingerprint_report():
    return {
        "curl_cffi": HAS_CFFI,
        "impersonate": IMPERSONATE if HAS_CFFI else None,
        "tls": "chrome131" if HAS_CFFI else "requests-default",
        "advice": (None if HAS_CFFI else
                   "pip install curl_cffi for Chrome TLS fingerprinting"),
    }
