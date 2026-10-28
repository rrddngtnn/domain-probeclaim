"""CLI entrypoint for accfarm."""
from __future__ import annotations

import argparse
import json
import sys

from .core import netpool, schedule
from .core.httpses import fingerprint_report
from .core.store import (backup, counts, current_ip, open_db, renew_queue,
                         upsert_tenant)


def cmd_doctor(args):
    print("== Environment ==")
    fp = fingerprint_report()
    print(f"  curl_cffi     : {fp['curl_cffi']}")
    print(f"  TLS profile   : {fp['tls']}")
    if fp["advice"]:
        print(f"  Advice        : {fp['advice']}")
    try:
        import fastapi  # noqa: F401
        print("  fastapi       : available (mock server enabled)")
    except ImportError:
        print("  fastapi       : missing (pip install fastapi uvicorn)")
    print(f"  Local time    : {schedule.now_local():%Y-%m-%d %H:%M}")
    print(f"  Quiet hours   : {'ACTIVE' if schedule.in_quiet_hours() else 'inactive'}")

    print("\n== Proxy Pool ==")
    pool = netpool.ProxyPool()
    print(f"  proxies.json  : {len(pool)} entries")
    if len(pool):
        pool.report()

    print("\n== Network ==")
    ip = current_ip()
    print(f"  Exit IP       : {ip or 'undetected'}")
    return 0


def cmd_route(args):
    pool = netpool.ProxyPool()
    route = netpool.resolve_route("cli-probe", pool=pool, mode=args.mode)
    print(json.dumps({
        "mode": route.mode,
        "proxy": "set" if route.proxy else None,
        "exit_ip": route.exit_ip,
        "budget_per_ip": route.budget,
        "window_days": route.window,
        "ok": route.ok,
        "error": route.error,
    }, indent=2))
    return 0 if route.ok else 2


def cmd_mock(args):
    import uvicorn
    from .mock_server import app
    uvicorn.run(app, host=args.host, port=args.port)
    return 0


def cmd_run(args):
    from .drivers.mock import MockDriver
    from .mailbox import MockMailbox
    from .runner import run_batch

    db = open_db(args.db)
    tid = upsert_tenant(db, "mock", "mock", payment="none")
    box = MockMailbox()
    results = run_batch(
        db, MockDriver, tid, count=args.count,
        mailbox=box, max_per_ip=args.max_per_ip,
        proxy_mode=args.mode, no_sleep=True,
        dry_run=args.dry,
        route=netpool.resolve_route("cli", mode=args.mode) if args.mode else None,
    )
    for r in results:
        print(json.dumps({k: v for k, v in r.items()}, default=str))
    return 0


def cmd_status(args):
    db = open_db(args.db)
    print(json.dumps(counts(db), indent=2))
    rq = renew_queue(db)
    print(f"\nExpiring within 45 days: {len(rq)}")
    for r in rq:
        print(f"  {r['fqdn']:32} {r['expires_at'] or '-'}")
    for r in db.execute("SELECT id,status,exit_ip,email FROM accounts "
                        "ORDER BY id LIMIT 20"):
        print(f"  #{r['id']:<4} {r['status']:10} {(r['exit_ip'] or '-'):16} {r['email']}")
    return 0


def build_parser():
    p = argparse.ArgumentParser(prog="accfarm")
    p.add_argument("--db", default="accfarm.db")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("doctor").set_defaults(fn=cmd_doctor)

    rt = sub.add_parser("route")
    rt.add_argument("--mode", default="auto",
                    choices=["auto", "pool", "direct"])
    rt.set_defaults(fn=cmd_route)

    mk = sub.add_parser("mock")
    mk.add_argument("--host", default="127.0.0.1")
    mk.add_argument("--port", type=int, default=8787)
    mk.set_defaults(fn=cmd_mock)

    run = sub.add_parser("run")
    run.add_argument("--count", type=int, default=1)
    run.add_argument("--mode", default="direct",
                     choices=["auto", "pool", "direct"])
    run.add_argument("--max-per-ip", type=int, default=3)
    run.add_argument("--dry", action="store_true")
    run.set_defaults(fn=cmd_run)

    sub.add_parser("status").set_defaults(fn=cmd_status)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
