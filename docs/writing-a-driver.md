# Menulis driver untuk layanan baru

Driver adalah satu-satunya tempat yang boleh tahu tentang target tertentu.
Semua yang ada di `core/`, `mailbox/`, dan `probe/` harus tetap netral.

## Langkah

### 1. Petakan alurnya dulu, jangan menulis kode

Rekam satu sesi manual di browser, ekspor HAR, lalu:

```python
from domainkit.probe.schema import parse_har
for r in parse_har("flow.har"):
    print(r["method"], r["status"], r["url"])
    for k, v in r["fields"].items():
        print("   ", k, "=", str(v)[:40])
```

Yang dicari: endpoint mana yang **POST**, field apa yang dikirim, dan apakah
ada field yang namanya tidak jelas asalnya (token, csrf, id).

### 2. Cari nama field dengan error-diffing

Kalau endpoint membalas error per-field, jangan menebak urutannya — biarkan
server yang menunjukkan:

```python
from domainkit.probe.schema import follow_missing, probe_fields

def call(payload):
    r = session.post(URL, json=payload)
    return r.status_code, r.text

# langkah 1: field mana yang berpengaruh?
base, found = probe_fields(call, ["domain", "fqdn", "domain_name", "sld"], "x.test")

# langkah 2: ikuti error missing_* sampai habis
status, payload, body = follow_missing(call, {}, VALUES)
```

`probe_fields` membandingkan error untuk satu field pada satu waktu. Field
yang **mengubah** error adalah field yang benar-benar dibaca; sisanya
diabaikan server.

Kalau error-nya `invalid_contact` untuk semua field tunggal, biasanya server
mengharapkan objek bersarang. Coba bungkus:
`{"contact": {...}}`, lalu perhatikan apakah errornya berubah menjadi
`missing_<field>` — di titik itu kamu sudah masuk.

### 3. Isi driver

```python
from domainkit.drivers.base import Capabilities, ClaimResult, RegistrarDriver
from domainkit.core.httpses import post_json


class ServiceDriver(RegistrarDriver):
    name = "service"
    base_url = "https://service.example"
    default_tld = "example.test"

    @property
    def caps(self):
        return Capabilities(payment="qris", gate="email")

    def _url(self, path):
        return self.base_url + path

    def signup(self, ident):
        r = post_json(self.session, self._url("/api/auth/signup"),
                      {"email": ident["email"], "password": ident["password"]})
        r.raise_for_status()
        return r.json()

    def save_contact(self, ident):
        r = post_json(self.session, self._url("/api/contacts"), {
            "first_name": ident["first_name"],
            "last_name": ident["last_name"],
            "email": ident["email"],
            "phone": ident["telepon"],
        })
        r.raise_for_status()
        return r.json()

    def claim(self, fqdn):
        r = post_json(self.session, self._url("/api/domains/register"),
                      {"domain_name": fqdn})
        body = r.json() if r.content else {}
        if r.status_code >= 400:
            return ClaimResult(ok=False, fqdn=fqdn,
                               error=body.get("error"), raw=body)
        return ClaimResult(ok=True, fqdn=fqdn,
                           expires_at=body.get("expires_at"),
                           epp=body.get("epp"), raw=body)
```

### 4. Deklarasikan kemampuan dengan jujur

`Capabilities(payment=..., gate=...)` menentukan apakah driver boleh jalan
otomatis:

| payment | arti |
|---|---|
| `none` | gratis, tanpa pembayaran |
| `balance` | saldo prepaid toko |
| `qris` / `bank` | transfer domestik |
| `voucher` | kode yang bisa dibeli terpisah |
| `card` | kartu — `unattended()` otomatis `False` |

| gate | arti |
|---|---|
| `none` | langsung bisa |
| `email` | butuh verifikasi email (bisa diotomasi lewat mailbox) |
| `kyc` | butuh dokumen identitas |
| `3ds` | butuh challenge dari issuer |
| `captcha` | butuh penyelesaian captcha |
| `manual_review` | order ditahan manusia |

Jangan tulis `payment="none"` kalau sebenarnya ada gerbang kartu di tengah
alur. Nilai itu dipakai untuk memutuskan, jadi salah isi = salah keputusan.

### 5. Uji tanpa jaringan

Tambahkan handler ke mock server yang meniru kontrak baru itu, lalu tulis tes
yang menembak mock. Kontrak yang diuji offline jauh lebih murah daripada
menembak layanan nyata.

## Jebakan yang sudah pernah ketemu

- **HTTP/2 upgrade di server tanpa TLS.** Kalau target `http://`, paksa
  `http_version="v1"`. Sudah ditangani `runner` otomatis.
- **Cookie sesi.** Client harus mempertahankan cookie antar request. Di tes,
  `TestClient` per-instance sudah mempertahankannya; jangan bikin client baru
  per request.
- **Field bernama `label` atau sejenisnya di level atas.** Kalau sebuah objek
  bersarang terus ditolak dengan "field X kosong" padahal X sudah di dalam
  objek, coba taruh X di level atas.
- **Nama field bahasa campur.** Backend sering memakai snake_case Inggris
  walau UI-nya bahasa lain. Ambil dari HAR, jangan dari label UI.
