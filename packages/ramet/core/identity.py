"""ramet.core.identity — seed -> identitas sintetis yang deterministik.

Kenapa seed: satu string menggerakkan SEMUA field. Kalau operasi perlu
dihentikan dan dilanjutkan besok, cukup simpan seed-nya. Tanpa ini tiap
run drift dan jejak akun mana milik siapa hilang.
"""
from __future__ import annotations

import datetime
import hashlib
import random

NAMA_DEPAN = [
    "Adi", "Bagas", "Candra", "Dimas", "Eko", "Fajar", "Gilang", "Hendra",
    "Irfan", "Joko", "Krisna", "Lutfi", "Made", "Naufal", "Oscar", "Putra",
    "Rafi", "Satria", "Teguh", "Umar", "Vino", "Wahyu", "Yoga", "Zaki",
    "Anisa", "Bella", "Citra", "Dewi", "Elsa", "Fitri", "Gita", "Hana",
]
NAMA_BELAKANG = [
    "Pratama", "Saputra", "Nugroho", "Wibowo", "Hidayat", "Setiawan",
    "Kurniawan", "Firmansyah", "Ramadhan", "Maulana", "Susanto", "Halim",
    "Anggraini", "Puspita", "Rahmawati", "Safitri",
]
# kota -> (provinsi, kodepos, prefiks seluler lazim di area itu)
KOTA = [
    ("Jakarta", "DKI Jakarta", "10110", "0812"),
    ("Bandung", "Jawa Barat", "40111", "0822"),
    ("Surabaya", "Jawa Timur", "60111", "0856"),
    ("Yogyakarta", "DI Yogyakarta", "55211", "0858"),
    ("Semarang", "Jawa Tengah", "50132", "0857"),
    ("Medan", "Sumatera Utara", "20111", "0813"),
    ("Makassar", "Sulawesi Selatan", "90111", "0851"),
    ("Denpasar", "Bali", "80231", "0819"),
    ("Malang", "Jawa Timur", "65111", "0855"),
    ("Palembang", "Sumatera Selatan", "30111", "0811"),
]
JALAN = ["Melati", "Kenanga", "Anggrek", "Cempaka", "Mawar", "Kamboja",
         "Flamboyan", "Seroja", "Dahlia", "Teratai"]
SUFFIX = ["!@#$%&*"]


def _rng(seed: str) -> random.Random:
    return random.Random(hashlib.sha256(seed.encode()).digest())


def _password(seed: str) -> str:
    """Sandi kuat-tapi-manusiawi, stabil per seed, tidak pernah di-log."""
    rng = _rng("pw:" + seed)
    kata = ["Nest", "Wire", "Tail", "Gnaw", "Stack", "Cube", "Flux", "Deep"]
    return (f"{rng.choice(kata)}{rng.randint(1000, 9999)}"
            f"{rng.choice(SUFFIX[0])}{rng.choice(kata).lower()}")


def make_identity(seed: str, email_domain: str = "example.test") -> dict:
    rng = _rng(seed)
    depan, belakang = rng.choice(NAMA_DEPAN), rng.choice(NAMA_BELAKANG)
    kota, prov, kodepos, prefix = rng.choice(KOTA)
    tag = rng.randint(10, 999)
    handle = f"{depan.lower()}{belakang.lower()}{tag}"
    lahir = datetime.date(rng.randint(1986, 2003), rng.randint(1, 12),
                          rng.randint(1, 28))
    return {
        "seed": seed,
        "nama": f"{depan} {belakang}",
        "first_name": depan,
        "last_name": belakang or "Pratama",
        "handle": handle,
        "email": f"{handle}@{email_domain}",
        "telepon": f"{prefix}{rng.randint(1000000, 9999999)}",
        "lahir": lahir.isoformat(),
        "lahir_dmy": lahir.strftime("%d/%m/%Y"),
        "kota": kota,
        "provinsi": prov,
        "kodepos": kodepos,
        "alamat": f"Jl. {rng.choice(JALAN)} No. {rng.randint(1, 220)}",
        "password": _password(seed),
    }


def redact(ident: dict) -> dict:
    """Buang sandi. Untuk log, cetak, dan penyimpanan publik."""
    return {k: v for k, v in ident.items() if k not in ("password",)}
