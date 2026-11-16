"""CLI entrypoint for domain_probeclaim."""
from __future__ import annotations

import argparse
import importlib
import json
import sys

from .adapters.resolve import ChainConfig, build_chain, explain_chain
from .adapters.solvers.cfast import CfastClient
from .core import netpool, schedule
from .core.httpses import fingerprint_report
from .core.sepa import generate_sepa_profile
from .core.store import (backup, counts, current_ip, open_db, renew_queue,
                         upsert_tenant)


def _load_driver(spec: str):
    if spec == "mock":
        from .drivers.mock import MockDriver
        return MockDriver
    if spec == "rdap":
        from .drivers.rdap import RdapDriver
        return RdapDriver
    if ":" in spec:
        mod_name, cls_name = spec.split(":", 1)
        mod = importlib.import_module(mod_name)
        return getattr(mod, cls_name)
    raise ValueError(f"Unknown driver {spec!r}; use mock, rdap, or pkg.mod:Class")


def _load_vouchers(args) -> list[str]:
    codes = list(getattr(args, "voucher", None) or [])
    vf = getattr(args, "vouchers_file", None)
    if vf:
        with open(vf, "r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if s and not s.startswith("#"):
                    codes.append(s)
    return codes


def _load_cards(args) -> list[dict]:
    cf = getattr(args, "cards_file", None)
    if not cf:
        return []
    with open(cf, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, list) else data.get("cards", [])


def _config_from_args(args) -> ChainConfig:
    return ChainConfig(
        locale=getattr(args, "locale", None),
        payment_override=getattr(args, "payment", None),
        gate_override=getattr(args, "gate", None),
        sepa_country=getattr(args, "sepa_country", "DE"),
        vouchers=_load_vouchers(args),
        cards=_load_cards(args),
        solver_url=getattr(args, "solver_url", None),
        cfast_bin=getattr(args, "cfast_bin", None),
        cfast_profile=getattr(args, "cfast_profile", None),
        claim_mode=getattr(args, "claim_mode", "auto"),
        targets=getattr(args, "target", None) or [],
    )


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

    cf = CfastClient()
    cf_health = cf.health()
    print("\n== Solver (cfast) ==")
    print(f"  binary        : {cf.bin_path or 'missing'}")
    print(f"  profile       : {cf.profile_path or 'missing'}")
    print(f"  api (:8810)   : {'LIVE' if cf_health else 'stopped'}")

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


def cmd_chain(args):
    from .mailbox import MockMailbox
    drv_cls = _load_driver(args.driver)
    cfg = _config_from_args(args)
    chain = build_chain(drv_cls().caps, mailbox=MockMailbox(), config=cfg)
    print(explain_chain(chain))
    return 0 if chain.ok else 2


def cmd_sepa(args):
    prof = generate_sepa_profile(args.seed, holder=args.holder, country=args.country)
    print(json.dumps(prof, indent=2))
    return 0


def cmd_run(args):
    from .mailbox import MockMailbox
    from .runner import run_batch

    drv_cls = _load_driver(args.driver)
    db = open_db(args.db)
    tid = upsert_tenant(db, drv_cls.name, drv_cls.name, payment=drv_cls().caps.payment)
    box = MockMailbox()
    cfg = _config_from_args(args)
    use_cfg = any([
        args.driver != "mock", args.locale, args.payment, args.gate,
        args.voucher, args.vouchers_file, args.cards_file,
        args.solver_url, args.cfast_bin, args.target,
        args.claim_mode != "auto",
    ])
    results = run_batch(
        db, drv_cls, tid, count=args.count,
        mailbox=box, max_per_ip=args.max_per_ip,
        quiet_hours=not args.ignore_quiet,
        proxy_mode=args.mode, no_sleep=True,
        dry_run=args.dry,
        route=netpool.resolve_route("cli", mode=args.mode) if args.mode else None,
        chain_config=cfg if use_cfg else None,
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


def _add_chain_flags(p):
    p.add_argument("--driver", default="mock")
    p.add_argument("--locale", default=None)
    p.add_argument("--payment", default=None)
    p.add_argument("--gate", default=None)
    p.add_argument("--sepa-country", default="DE")
    p.add_argument("--voucher", action="append", default=[])
    p.add_argument("--vouchers-file", default=None)
    p.add_argument("--cards-file", default=None)
    p.add_argument("--solver-url", default=None)
    p.add_argument("--cfast-bin", default=None)
    p.add_argument("--cfast-profile", default=None)
    p.add_argument("--claim-mode", default="auto",
                   choices=["auto", "promo", "direct", "differ", "readonly"])
    p.add_argument("--target", action="append", default=[])


def build_parser():
    p = argparse.ArgumentParser(prog="domain_probeclaim")
    p.add_argument("--db", default="domain_probeclaim.db")
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

    ch = sub.add_parser("chain")
    _add_chain_flags(ch)
    ch.set_defaults(fn=cmd_chain)

    sp = sub.add_parser("sepa")
    sp.add_argument("--seed", default="demo-seed-1")
    sp.add_argument("--country", default="DE", choices=["DE", "NL", "FR", "AT"])
    sp.add_argument("--holder", default="")
    sp.set_defaults(fn=cmd_sepa)

    run = sub.add_parser("run")
    run.add_argument("--count", type=int, default=1)
    run.add_argument("--mode", default="direct",
                     choices=["auto", "pool", "direct"])
    run.add_argument("--max-per-ip", type=int, default=3)
    run.add_argument("--dry", action="store_true")
    run.add_argument("--ignore-quiet", action="store_true")
    _add_chain_flags(run)
    run.set_defaults(fn=cmd_run)

    sub.add_parser("status").set_defaults(fn=cmd_status)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
