"""Deterministic SEPA IBAN, BIC, and mandate profile generator (ISO 13616)."""
from __future__ import annotations

import datetime
import hashlib
import random

# (country_code, bban_length, bank_specs: [(bank_code, bic, bank_name), ...], acct_digits)
SEPA_SPECS = {
    "DE": {
        "bban_len": 18,
        "acct_len": 10,
        "banks": [
            ("10010010", "PBNKDEFF", "Postbank Berlin"),
            ("12030000", "BYLADEM1001", "DKB Berlin"),
            ("37040044", "COBADEFFXXX", "Commerzbank Koeln"),
            ("50010517", "INGDDEFFXXX", "ING-DiBa Frankfurt"),
            ("10011001", "NTSBDEB1XXX", "N26 Bank Berlin"),
            ("70020270", "HYVEDEMMXXX", "HypoVereinsbank Muenchen"),
        ],
    },
    "NL": {
        "bban_len": 14,
        "acct_len": 10,
        "banks": [
            ("INGB", "INGBNL2A", "ING Bank"),
            ("RABO", "RABONL2U", "Rabobank"),
            ("ABNA", "ABNANL2A", "ABN AMRO"),
            ("BUNQ", "BUNQNL2A", "bunq"),
        ],
    },
    "FR": {
        "bban_len": 23,
        "acct_len": 11,
        "banks": [
            ("3000400003", "BNPAFRPP", "BNP Paribas"),
            ("3000600001", "AGRIFRPP", "Credit Agricole"),
            ("2004100001", "PSSTFRPPPAR", "La Banque Postale"),
        ],
    },
    "AT": {
        "bban_len": 16,
        "acct_len": 11,
        "banks": [
            ("20111", "GIBAATWWXXX", "Erste Bank"),
            ("32000", "RLNWATWWXXX", "Raiffeisen"),
            ("14000", "BAWAATWWXXX", "BAWAG"),
        ],
    },
}


def _iban_numeric(raw: str) -> str:
    """Expand letters A-Z to 10-35 for ISO 7064 MOD-97-10 calculation."""
    out = []
    for ch in raw.upper():
        if ch.isdigit():
            out.append(ch)
        elif "A" <= ch <= "Z":
            out.append(str(ord(ch) - ord("A") + 10))
    return "".join(out)


def _mod97(num_str: str) -> int:
    rem = 0
    for ch in num_str:
        rem = (rem * 10 + int(ch)) % 97
    return rem


def iban_check_digits(country: str, bban: str) -> str:
    """Compute 2-digit ISO 13616 check digits for country + BBAN."""
    cc = country.upper()
    if len(cc) != 2 or not cc.isalpha():
        raise ValueError(f"Invalid country code: {country!r}")
    rearranged = f"{bban}{cc}00"
    digits = _iban_numeric(rearranged)
    check = 98 - _mod97(digits)
    return f"{check:02d}"


def validate_iban(iban: str) -> bool:
    """Verify length/characters and ISO 7064 MOD-97-10 checksum == 1."""
    clean = "".join(iban.split()).upper()
    if len(clean) < 15 or len(clean) > 34 or not clean[:2].isalpha():
        return False
    if not clean[2:4].isdigit() or not clean[4:].isalnum():
        return False
    rearranged = clean[4:] + clean[:4]
    return _mod97(_iban_numeric(rearranged)) == 1


def format_iban(iban: str) -> str:
    clean = "".join(iban.split()).upper()
    return " ".join(clean[i:i + 4] for i in range(0, len(clean), 4))


def _fr_rib_key(bank_branch: str, acct: str) -> str:
    """Compute 2-digit French RIB control key."""
    table = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ",
                          "12345678912345678923456789")
    b = int(bank_branch[:5])
    g = int(bank_branch[5:10])
    c = int(acct.upper().translate(table))
    key = 97 - ((89 * b + 15 * g + 3 * c) % 97)
    return f"{key:02d}"


def generate_iban(seed: str, country: str = "DE") -> dict:
    """Deterministically generate a syntactically & MOD-97 valid SEPA IBAN + BIC."""
    cc = country.upper()
    spec = SEPA_SPECS.get(cc)
    if not spec:
        raise ValueError(f"Unsupported SEPA country: {country!r} "
                         f"(supported: {', '.join(sorted(SEPA_SPECS))})")
    rng = random.Random(hashlib.sha256(f"sepa:{cc}:{seed}".encode()).digest())
    bank_code, bic, bank_name = rng.choice(spec["banks"])
    acct = "".join(str(rng.randint(0, 9)) for _ in range(spec["acct_len"]))

    if cc == "FR":
        bban = f"{bank_code}{acct}{_fr_rib_key(bank_code, acct)}"
    else:
        bban = f"{bank_code}{acct}"

    check = iban_check_digits(cc, bban)
    iban = f"{cc}{check}{bban}"
    return {
        "country": cc,
        "iban": iban,
        "iban_formatted": format_iban(iban),
        "bic": bic,
        "bank_code": bank_code,
        "bank_name": bank_name,
        "account_number": acct,
        "valid": validate_iban(iban),
    }


def generate_sepa_profile(seed: str, holder: str = "",
                          country: str = "DE") -> dict:
    """Full SEPA Direct Debit profile including mandate reference & signed date."""
    info = generate_iban(seed, country=country)
    digest = hashlib.sha256(f"mandate:{seed}:{info['iban']}".encode()).hexdigest()
    info["account_holder"] = holder or f"Konto {digest[:8].upper()}"
    info["mandate_ref"] = f"MND-{country.upper()}-{digest[:12].upper()}"
    info["signed_at"] = datetime.date.today().isoformat()
    return info
