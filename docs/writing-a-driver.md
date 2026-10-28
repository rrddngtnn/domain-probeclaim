# Writing a Driver

A driver encapsulates target-specific API endpoints, mutations, and authentication. Core modules (`core/`, `mailbox/`, and `probe/`) remain target-agnostic.

## Implementation Steps

### 1. Map Network Traffic

Export a clean HAR file from a representative browser session:

```python
from sybil.probe.schema import parse_har

for entry in parse_har("flow.har"):
    print(entry["method"], entry["status"], entry["url"])
    for k, v in entry["fields"].items():
        print("   ", k, "=", str(v)[:40])
```

Identify state-mutating requests (`POST`/`PUT`), payload schema variations, and dynamically generated tokens (CSRF, session identifiers).

### 2. Infer Payload Schema via Differential Probing

When APIs fail with single-field validation errors, discover required properties systematically:

```python
from sybil.probe.schema import follow_missing, probe_fields

def call(payload):
    r = session.post(URL, json=payload)
    return r.status_code, r.text

# 1. Identify active candidate keys
base, active_fields = probe_fields(call, ["domain", "fqdn", "domain_name", "sld"], "sample.test")

# 2. Incrementally satisfy validation requirements
status, final_payload, body = follow_missing(call, {}, KNOWN_VALUES)
```

`probe_fields` monitors response error differentials. When a submitted field changes the returned error code, that field is actively evaluated by server validation.

If payloads return broad validation errors (e.g. `invalid_contact`), the server likely expects nested structures such as `{"contact": {...}}`.

### 3. Implement Driver Class

```python
from sybil.drivers.base import Capabilities, ClaimResult, RegistrarDriver
from sybil.core.httpses import post_json


class ServiceDriver(RegistrarDriver):
    name = "service"
    base_url = "https://service.example"
    default_tld = "example.test"

    @property
    def caps(self):
        return Capabilities(payment="none", gate="email")

    def _url(self, path):
        return self.base_url + path

    def signup(self, ident):
        r = post_json(self.session, self._url("/api/auth/signup"), {
            "email": ident["email"],
            "password": ident["password"],
        })
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
        r = post_json(self.session, self._url("/api/domains/register"), {
            "domain_name": fqdn,
        })
        body = r.json() if r.content else {}
        if r.status_code >= 400:
            return ClaimResult(ok=False, fqdn=fqdn, error=body.get("error"), raw=body)
        return ClaimResult(ok=True, fqdn=fqdn, expires_at=body.get("expires_at"),
                           epp=body.get("epp"), raw=body)
```

### 4. Declare Operational Constraints

Capabilities define whether automated runs can proceed without human intervention:

| `payment` | Description |
|---|---|
| `none` | Free tier / promo without payment gateway |
| `balance` | Internal prepaid balance |
| `card` | Card processing — automatically sets `unattended=False` |
| `crypto` | Native crypto settlement |

| `gate` | Description |
|---|---|
| `none` | Instant registration |
| `email` | Email verification link or OTP required |
| `kyc` | Identity verification barrier |
| `3ds` | Interactive 3DS challenge |
| `captcha` | Interactive or automated captcha solver required |
| `manual_review` | Queued for manual administrative approval |

### 5. Validate with In-Memory Mock Server

Add endpoint handlers to `mock_server.py` representing target behavior and write offline tests before issuing live network requests.
