# ramet

Toolkit Python untuk menjalankan **banyak identitas sintetis terhadap satu
layanan** — dengan state SQLite yang bisa diaudit, routing proxy per
identitas, jadwal berjitter, dan schema discovery lewat error-diffing.

Repo ini **tidak netral**, dan tidak berpura-pura netral. Isinya adalah
komponen yang berguna ketika satu operator perlu mengelola banyak identitas:
pembuat identitas deterministik, penjaga budget per IP, penjadwal manusiawi,
dan pencatat event. Nama "ramet" diambil dari biologi: satu koloni klonal
menghasilkan banyak **ramet** — individu-individu identik secara genetik,
masing-masing berdiri sendiri. Itu persis mekanisme yang diimplementasikan
kode ini: satu seed menghasilkan satu identitas, deterministik, dan library
ini mengelola banyak di antaranya berdampingan dengan rute jaringan dan
catatan masing-masing.

Kalau yang kamu butuhkan cuma schema discovery, ambil `probe/schema.py` saja;
itu satu-satunya modul yang berdiri sendiri tanpa asumsi multi-identitas.


```
             ┌──────────────────────────────────────────┐
             │  driver (pengetahuan tentang 1 target)   │
             └───────────────────┬──────────────────────┘
                                 │
      ┌──────────────────────────┼──────────────────────────┐
      │                          │                          │
┌─────▼─────┐            ┌───────▼───────┐          ┌───────▼───────┐
│  httpses  │            │    netpool    │          │    mailbox    │
│ TLS/header│            │ proxy/direct  │          │ mock/temp/imap│
└─────┬─────┘            └───────┬───────┘          └───────────────┘
      │                          │
      └──────────┬───────────────┘
                 │
         ┌───────▼────────┐        ┌────────────┐
         │     runner     │───────▶│   store    │
         │ orkestrasi     │        │ sqlite     │
         └────────────────┘        └────────────┘
```

## Kenapa ada

Kalau kamu pernah perlu memetakan alur registrasi sebuah layanan — untuk
integrasi, QA, riset, atau bikin tooling sendiri — yang sulit bukan
menulis kode HTTP-nya. Yang sulit:

- tahu **field mana** yang benar-benar dibaca server
- menjaga **identitas tetap konsisten** antar sesi
- mencatat **apa yang sudah dilakukan** supaya bisa diulang dan diaudit
- menjaga **jejak jaringan** tidak berantakan

ramet mengangkat empat hal itu jadi komponen terpisah yang bisa diuji.

## Pasang

```bash
git clone <repo> ramet && cd ramet
python3 -m pip install -e ".[dev]"
```

Atau tanpa install, cukup `PYTHONPATH=packages` (ada `Makefile`).

## Mulai cepat — tanpa jaringan sama sekali

Mock server meniru *pola*, bukan vendor: validasi berurutan yang membalas
satu error per request, kontak wajib sebelum klaim, jatah per akun, 409 untuk
nama terpakai.

```bash
make mock          # terminal 1: mock registrar di 127.0.0.1:8787
make run N=2       # terminal 2: dua akun -> dua domain, mode tanpa proxy
make test          # 57 tes, semuanya offline
```

Contoh keluaran `make run`:

```json
{"seed": "...-0", "mode": "direct", "exit_ip": "203.0.113.7",
 "claimed": "laci49621.example.test", "expires": "2027-10-28", "epp": "E000004"}
```

## Dua mode jaringan — ini yang dijaga ketat

Satu antarmuka, dua perilaku. Driver tidak pernah tahu mana yang dipakai.

```bash
ramet route --mode direct   # tidak pakai proxy
ramet route --mode pool     # wajib proxy; gagal kalau pool kosong/mati
ramet route --mode auto     # pakai pool kalau ada isinya, kalau tidak direct
```

| | `direct` | `pool` |
|---|---|---|
| `proxies.json` | diabaikan | wajib, minimal 1 hidup |
| `exit_ip` | IP publik mesin | IP keluar proxy |
| budget akun per IP | 2 / 7 hari | 3 / 7 hari |
| proxy mati | tidak relevan | **berhenti**, jangan lanjut |

Yang penting: **`direct` bukan mode "rusak"**. `exit_ip` tetap dideteksi dan
tetap masuk guard, jadi kamu tahu persis berapa akun yang sudah keluar dari
alamat itu. Bedanya cuma budget lebih kecil, karena semua akun berbagi satu
alamat.

Format `proxies.json`:

```json
{"proxies": [
  {"url": "http://user:pass@host:port", "kind": "residential"},
  {"url": "http://user:pass@host:port", "kind": "mobile"}
]}
```

`kind` berbobot saat alokasi: `mobile` 3.0, `residential` 2.0, `isp` 1.5,
`datacenter` 0.4. Alokasi **deterministik per seed** — seed yang sama selalu
dapat proxy yang sama, karena memindahkan IP di tengah umur satu identitas
lebih berisiko daripada berbagi IP antar identitas.

## Schema discovery

Server yang membalas error satu per satu bisa dipakai sebagai peta.
`probe.schema` mengikuti jejak itu:

```python
from ramet.probe.schema import follow_missing, probe_fields

def call(payload):
    r = session.post(url, json=payload)
    return r.status_code, r.json()

status, payload, body = follow_missing(
    call, {}, {"first_name": "A", "last_name": "B", "email": "a@b.test"})
# berhenti saat status bukan lagi missing_*
```

Kalau error-nya tidak menyebut nama field, `probe_fields` membandingkan
respons untuk satu field pada satu waktu dan melaporkan mana yang mengubah
error — yaitu mana yang benar-benar dibaca.

## Menulis driver

```python
from ramet.drivers.base import Capabilities, ClaimResult, RegistrarDriver

class MyDriver(RegistrarDriver):
    name = "myservice"
    base_url = "https://example.test"
    default_tld = "example.test"

    @property
    def caps(self):
        return Capabilities(payment="balance", gate="email")

    def signup(self, ident): ...
    def save_contact(self, ident): ...
    def claim(self, fqdn) -> ClaimResult: ...
    def list_domains(self): ...
```

`capabilities.payment` dan `.gate` dipakai runner untuk memutuskan apakah
driver bisa jalan unattended. `unattended()` mengembalikan `False` untuk
`payment="card"` dan untuk gate `kyc`/`3ds`/`captcha`/`manual_review` —
bukan larangan, tapi penanda bahwa jalur itu butuh manusia atau sandbox PSP.

## CLI

```
ramet doctor                 # lingkungan, TLS, proxy, IP keluar
ramet route --mode auto      # keputusan routing
ramet mock                   # mock registrar
ramet run --count 2          # jalankan melawan mock
ramet status                 # isi database
```

## Tes

```bash
python3 -m pytest            # 57 tes, offline
```

Yang diuji:

- `identity` deterministik per seed, sandi memenuhi aturan minimum
- `store` schema, event, renew queue, **guard IP** (hitungan, status `dead`,
  batas window)
- `routing` **ketiga mode**, budget beda, `exit_ip` tetap terisi di mode
  direct, proxy mati menggagalkan `pool`
- `mock server` kontrak: signup, 409, jatah, TLD, kontak bertahap
- `runner` dua mode sampai domain, guard menghentikan batch
- `mailbox` inject + wait + timeout
- `probe` follow_missing dan probe_fields

Tidak ada satu pun tes yang membuka socket ke internet.

## Struktur

```
packages/ramet/
├── core/
│   ├── identity.py     seed -> identitas deterministik
│   ├── store.py        sqlite: tenants/accounts/domains/events + guard IP
│   ├── netpool.py      ProxyPool + Route  <- satu-satunya yang tahu proxy
│   ├── httpses.py      sesi HTTP/TLS konsisten (curl_cffi, fallback requests)
│   └── schedule.py     jitter, jeda, jam tenang
├── mailbox/            mock | tempmail-api | imap-catchall
├── probe/schema.py     error-diffing, HAR parser
├── drivers/            base kontrak + mock
├── runner.py           orkestrasi akun -> kontak -> klaim
├── mock_server.py      registrar tiruan (FastAPI)
└── cli.py
```

## Catatan teknis yang ditemukan saat membangun

- **curl_cffi + server lokal tanpa TLS**: profil impersonate mengirim
  `Upgrade: h2c`. Server pengembangan yang tidak paham h2c akan kehilangan
  body request dan membalas error. Runner memaksa `http_version="v1"` untuk
  target `http://` saja; untuk `https://` ALPN berjalan normal.
- **JSON diserialisasi eksplisit** di `httpses.post_json`, bukan diserahkan
  ke `json=`, supaya perilakunya sama di curl_cffi, requests, dan test client.
- **Perbandingan waktu di store pakai string ISO UTC**, karena SQLite tidak
  punya tipe waktu. Semua timestamp ditulis dengan format yang sama.
