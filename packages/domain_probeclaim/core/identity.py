"""Deterministic synthetic identity generation from a seed string."""
from __future__ import annotations

import datetime
import hashlib
import random

FIRST_NAMES = [
    "Adi", "Bagas", "Candra", "Dimas", "Eko", "Fajar", "Gilang", "Hendra",
    "Irfan", "Joko", "Krisna", "Lutfi", "Made", "Naufal", "Oscar", "Putra",
    "Rafi", "Satria", "Teguh", "Umar", "Vino", "Wahyu", "Yoga", "Zaki",
    "Anisa", "Bella", "Citra", "Dewi", "Elsa", "Fitri", "Gita", "Hana",
]
LAST_NAMES = [
    "Pratama", "Saputra", "Nugroho", "Wibowo", "Hidayat", "Setiawan",
    "Kurniawan", "Firmansyah", "Ramadhan", "Maulana", "Susanto", "Halim",
    "Anggraini", "Puspita", "Rahmawati", "Safitri",
]
# City -> (State/Province, Postal Code, Phone Area Prefix)
CITIES = [
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
STREETS = ["Melati", "Kenanga", "Anggrek", "Cempaka", "Mawar", "Kamboja",
           "Flamboyan", "Seroja", "Dahlia", "Teratai"]
SUFFIX = ["!@#$%&*"]


DE_FIRST_NAMES = [
    "Lukas", "Leon", "Finn", "Jonas", "Maximilian", "Felix", "Paul", "Julian",
    "Tim", "Moritz", "Niklas", "Jan", "Tobias", "Stefan", "Hannah", "Mia",
    "Emma", "Sofia", "Lena", "Anna", "Laura", "Lea", "Julia", "Marie",
]
DE_LAST_NAMES = [
    "Mueller", "Schmidt", "Schneider", "Fischer", "Weber", "Meyer", "Wagner",
    "Becker", "Schulz", "Hoffmann", "Schaefer", "Koch", "Bauer", "Richter",
    "Klein", "Wolf", "Schroeder", "Neumann", "Schwarz", "Zimmermann",
]
# City -> (Bundesland, PLZ, Phone Prefix)
DE_CITIES = [
    ("Berlin", "Berlin", "10115", "+4930"),
    ("Hamburg", "Hamburg", "20095", "+4940"),
    ("Muenchen", "Bayern", "80331", "+4989"),
    ("Koeln", "Nordrhein-Westfalen", "50667", "+49221"),
    ("Frankfurt am Main", "Hessen", "60311", "+4969"),
    ("Stuttgart", "Baden-Wuerttemberg", "70173", "+49711"),
    ("Duesseldorf", "Nordrhein-Westfalen", "40213", "+49211"),
    ("Leipzig", "Sachsen", "04109", "+49341"),
]
DE_STREETS = [
    "Hauptstrasse", "Bahnhofstrasse", "Gartenstrasse", "Schulstrasse",
    "Lindenstrasse", "Bergstrasse", "Kirchstrasse", "Waldstrasse",
    "Friedrichstrasse", "Goethestrasse",
]


def _rng(seed: str) -> random.Random:
    return random.Random(hashlib.sha256(seed.encode()).digest())


def _password(seed: str) -> str:
    """Stable per-seed credentials."""
    rng = _rng("pw:" + seed)
    words = ["Nest", "Wire", "Tail", "Gnaw", "Stack", "Cube", "Flux", "Deep"]
    return (f"{rng.choice(words)}{rng.randint(1000, 9999)}"
            f"{rng.choice(SUFFIX[0])}{rng.choice(words).lower()}")


def make_identity(seed: str, email_domain: str = "example.test",
                  locale: str = "id") -> dict:
    rng = _rng(seed)
    loc = (locale or "id").lower()
    if loc in ("de", "eu"):
        first, last = rng.choice(DE_FIRST_NAMES), rng.choice(DE_LAST_NAMES)
        city, prov, postal, prefix = rng.choice(DE_CITIES)
        street = f"{rng.choice(DE_STREETS)} {rng.randint(1, 145)}"
        country = "DE"
        phone = f"{prefix}{rng.randint(1000000, 99999999)}"
    else:
        first, last = rng.choice(FIRST_NAMES), rng.choice(LAST_NAMES)
        city, prov, postal, prefix = rng.choice(CITIES)
        street = f"Jl. {rng.choice(STREETS)} No. {rng.randint(1, 220)}"
        country = "ID"
        phone = f"{prefix}{rng.randint(1000000, 9999999)}"

    tag = rng.randint(10, 999)
    handle = f"{first.lower()}{last.lower()}{tag}"
    dob = datetime.date(rng.randint(1986, 2003), rng.randint(1, 12),
                        rng.randint(1, 28))
    return {
        "seed": seed,
        "locale": loc,
        "country": country,
        "nama": f"{first} {last}",
        "first_name": first,
        "last_name": last or "Pratama",
        "handle": handle,
        "email": f"{handle}@{email_domain}",
        "telepon": phone,
        "lahir": dob.isoformat(),
        "lahir_dmy": dob.strftime("%d/%m/%Y"),
        "kota": city,
        "provinsi": prov,
        "kodepos": postal,
        "alamat": street,
        "password": _password(seed),
    }


def redact(ident: dict) -> dict:
    """Strip password for logging and telemetry."""
    return {k: v for k, v in ident.items() if k not in ("password",)}
