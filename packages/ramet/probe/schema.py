"""ramet.probe.schema — schema discovery lewat error-diffing.

Ide intinya: banyak REST API membalas error satu per satu. Dengan mengirim
satu field pada satu waktu dan membandingkan kode error, kita bisa tahu
field mana yang dibaca server tanpa pernah menebak buta.

Netral: fungsi di sini tidak tahu endpoint, field, atau vendor. Semua
masukan lewat parameter.
"""
from __future__ import annotations

import json
import random
import time


def classify(body) -> str:
    """Ambil kunci error dari body apa pun."""
    if isinstance(body, dict):
        return str(body.get("error") or body.get("message") or "ok")
    try:
        j = json.loads(body)
        if isinstance(j, dict):
            return str(j.get("error") or j.get("message") or "ok")
    except (ValueError, TypeError):
        pass
    return str(body)[:60]


def probe_fields(call, candidates: list[str], sample_value, baseline=None,
                 delay=(0.0, 0.0), sleep=time.sleep, log=None):
    """Kirim satu field per panggilan; laporkan yang mengubah error.

    call(payload) -> (status, body)
    Return (baseline_error, {field: (status, error)})
    """
    found = {}
    base = baseline
    for f in candidates:
        if delay and delay[1] > 0:
            sleep(random.uniform(*delay))
        payload = {f: sample_value(f) if callable(sample_value) else sample_value}
        status, body = call(payload)
        k = classify(body)
        if base is None:
            base = k
        if k != base:
            found[f] = (status, k)
        if log:
            log(f, status, k)
    return base, found


def follow_missing(call, initial: dict, values: dict, max_steps=30,
                   delay=(0.0, 0.0), sleep=time.sleep, log=None):
    """Ikuti error `missing_*` sampai tidak ada lagi, mengisi field yang
    diminta. Ini yang mengubah penebakan jadi pemetaan.

    call(payload) -> (status, body)
    values: peta field -> nilai yang akan dipakai
    Return (status_akhir, payload_akhir, body_akhir)
    """
    payload = dict(initial)
    status, body = None, None
    for step in range(max_steps):
        if delay and delay[1] > 0:
            sleep(random.uniform(*delay))
        status, body = call(payload)
        k = classify(body)
        if log:
            log(step + 1, status, k)
        if not k.startswith("missing_"):
            break
        field = k[len("missing_"):]
        if field not in values:
            # tidak ada nilai kandidat: pakai placeholder supaya bisa maju,
            # tapi catat. Pemanggil yang memutuskan berarti atau tidak.
            payload[field] = f"placeholder-{field}"
            continue
        payload[field] = values[field]
    return status, payload, body


def parse_har(path: str) -> list[dict]:
    """Ambil request non-asset dari file HAR. Untuk memetakan alur manual."""
    with open(path) as f:
        entries = json.load(f)["log"]["entries"]
    out = []
    skip = (".css", ".js", ".png", ".jpg", ".svg", ".woff", ".ico", ".webp", ".map")
    for e in entries:
        req, res = e["request"], e["response"]
        url = req["url"]
        if any(x in url for x in skip):
            continue
        fields = {}
        pd = req.get("postData") or {}
        text = pd.get("text") or ""
        if "json" in (pd.get("mimeType") or ""):
            try:
                fields = json.loads(text)
            except ValueError:
                fields = {"_raw": text[:200]}
        elif text:
            from urllib.parse import parse_qs
            fields = {k: v[0] for k, v in parse_qs(text, keep_blank_values=True).items()}
        out.append({"method": req["method"], "url": url,
                    "status": res["status"], "fields": fields})
    return out
