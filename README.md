# sybil

Deterministic synthetic identity orchestration, sticky network routing, and differential schema discovery.

sybil provides tools for automated registration pipelines, multi-identity account lifecycles, and reverse-engineering undocumented API endpoints.

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
git clone <repo> sybil && cd sybil
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
from sybil.probe.schema import follow_missing, probe_fields

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
sybil doctor                 # Inspect runtime environment, TLS profiles, and proxies
sybil route --mode auto      # Evaluate routing decisions
sybil mock                   # Start in-memory mock service
sybil run --count 2          # Run automated registration batch
sybil status                 # Display database summary
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
