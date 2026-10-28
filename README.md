# domain-probeclaim

Undocumented registrar schema discovery and automated batch promo claim engine.

`domain-probeclaim` is scoped specifically for reverse-engineering closed registrar registration endpoints and executing automated promo claims:

1. **Differential Error Probing (`probe.schema`)**: Map missing contact and registration parameters by diffing API error validation chains (`missing_contact` -> `missing_first_name` -> `missing_label`).
2. **Deterministic Identity Seeding (`core.identity`)**: Generate valid localized WHOIS profiles from a single seed.
3. **Sticky Route & IP Guard (`core.netpool`, `core.store`)**: Proxy-to-identity binding with strict per-IP budget pacing.
4. **Automated Claim & Quota Handling (`runner`)**: Pipeline handling disposable email verification, contact submission, promo slot claim (stopping upon quota exhaustion / `402`), and EPP code extraction into SQLite.

```
             ┌──────────────────────────────────────────┐
             │         driver (target-specific)         │
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
         │ pipeline engine│        │ sqlite     │
         └────────────────┘        └────────────┘
```

## Features

- **Deterministic Identity Generation**: Stable account attributes derived from a single seed string.
- **Sticky Route Management**: Stable proxy-to-identity binding with fail-closed proxy modes and automated direct fallback.
- **Differential Schema Discovery**: Infer undocumented API request requirements by tracing `missing_*` error responses.
- **Auditable SQLite Persistence**: Local event sourcing tracking every network transition and account state change.
- **Offline Mock Environment**: In-memory mock server simulating multi-step validation patterns without external network calls.

## Installation

```bash
git clone <repo> domain_probeclaim && cd domain_probeclaim
python3 -m pip install -e ".[dev]"
```

Or run directly without installing:

```bash
export PYTHONPATH=packages
```

## Quickstart

Run against the local offline mock environment:

```bash
# Terminal 1: Launch mock server at 127.0.0.1:8787
make mock

# Terminal 2: Run batch account registration pipeline
make run N=2

# Run offline test suite
make test
```

Sample pipeline output:

```json
{
  "seed": "20261028143000-0-7a8b9c",
  "mode": "direct",
  "exit_ip": "203.0.113.7",
  "claimed": "archive49621.example.test",
  "expires": "2027-10-28",
  "epp": "E000004"
}
```

## Network Routing Modes

Routing logic is decoupled from target drivers:

| Mode | `proxies.json` | Egress IP | Budget per IP | Behavior on Proxy Failure |
|---|---|---|---|---|
| `direct` | Ignored | Local machine public IP | 2 / 7 days | N/A |
| `pool` | Required (≥1 active) | Assigned proxy IP | 3 / 7 days | Terminate execution (exit 2) |
| `auto` | Optional | Proxy IP if available, else local IP | Dynamic | Fallback to direct |

Configuration in `proxies.json`:

```json
{
  "proxies": [
    {"url": "http://user:pass@host:port", "kind": "residential"},
    {"url": "http://user:pass@host:port", "kind": "mobile"}
  ]
}
```

Proxies are deterministically assigned based on the identity seed to avoid mid-lifecycle IP changes.

## Differential Schema Discovery

When target APIs return granular validation errors, `probe.schema` extracts the expected JSON schema automatically:

```python
from domain_probeclaim.probe.schema import follow_missing, probe_fields

def call(payload):
    r = session.post(url, json=payload)
    return r.status_code, r.json()

status, payload, body = follow_missing(
    call,
    initial={},
    values={"first_name": "A", "last_name": "B", "email": "a@b.test"}
)
```

## CLI Usage

```bash
domain_probeclaim doctor                 # Inspect runtime environment, TLS profiles, and proxies
domain_probeclaim route --mode auto      # Evaluate routing decisions
domain_probeclaim mock                   # Start in-memory mock service
domain_probeclaim run --count 2          # Run automated registration batch
domain_probeclaim status                 # Display database summary
```

## Test Suite

```bash
python3 -m pytest
```

57 unit and integration tests covering:
- Deterministic identity generation
- IP guard budget limits and retention windows
- Proxy pool assignment and direct routing fallback
- Sequential validation and domain allocation in mock registrar
- Mailbox polling and regex verification
- HTTP/1.1 downgrade enforcement for unencrypted endpoints
