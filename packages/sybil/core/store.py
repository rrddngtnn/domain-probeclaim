"""SQLite persistence for multi-identity tenants, accounts, and telemetry."""
from __future__ import annotations

import datetime
import os
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS tenants (
  id        INTEGER PRIMARY KEY,
  name      TEXT UNIQUE NOT NULL,
  driver    TEXT NOT NULL,
  payment   TEXT DEFAULT 'unknown',
  notes     TEXT
);

CREATE TABLE IF NOT EXISTS accounts (
  id            INTEGER PRIMARY KEY,
  tenant_id     INTEGER REFERENCES tenants(id),
  seed          TEXT NOT NULL,
  label         TEXT,
  email         TEXT NOT NULL,
  email_token   TEXT,
  email_expires TEXT,
  proxy         TEXT,
  exit_ip       TEXT,
  status        TEXT DEFAULT 'new',
  created_at    TEXT,
  last_action   TEXT,
  UNIQUE(tenant_id, seed)
);

CREATE TABLE IF NOT EXISTS domains (
  id            INTEGER PRIMARY KEY,
  account_id    INTEGER REFERENCES accounts(id),
  fqdn          TEXT UNIQUE NOT NULL,
  tld           TEXT,
  registered_at TEXT,
  expires_at    TEXT,
  epp           TEXT,
  ns1           TEXT,
  ns2           TEXT,
  status        TEXT DEFAULT 'active'
);

CREATE TABLE IF NOT EXISTS events (
  id         INTEGER PRIMARY KEY,
  ts         TEXT NOT NULL,
  account_id INTEGER,
  kind       TEXT NOT NULL,
  detail     TEXT
);

CREATE INDEX IF NOT EXISTS ix_dom_exp ON domains(expires_at);
CREATE INDEX IF NOT EXISTS ix_ev_acc  ON events(account_id);
CREATE INDEX IF NOT EXISTS ix_ev_ts   ON events(ts);
CREATE INDEX IF NOT EXISTS ix_acc_st  ON accounts(status);
CREATE INDEX IF NOT EXISTS ix_acc_ip  ON accounts(exit_ip, created_at);
"""

STATUSES = ("new", "pending", "needs_verify", "active", "flagged", "dead")


def utcnow() -> str:
    return (datetime.datetime.now(datetime.timezone.utc)
            .strftime("%Y-%m-%dT%H:%M:%SZ"))


def open_db(path: str = "sybil.db") -> sqlite3.Connection:
    db = sqlite3.connect(path)
    db.executescript(SCHEMA)
    db.row_factory = sqlite3.Row
    return db


def log(db, account_id, kind, detail=""):
    db.execute("INSERT INTO events(ts,account_id,kind,detail) VALUES(?,?,?,?)",
               (utcnow(), account_id, kind, str(detail)[:2000]))
    db.commit()


def upsert_tenant(db, name, driver, payment="unknown", notes=None) -> int:
    row = db.execute("SELECT id FROM tenants WHERE name=?", (name,)).fetchone()
    if row:
        return row["id"]
    cur = db.execute("INSERT INTO tenants(name,driver,payment,notes) "
                     "VALUES(?,?,?,?)", (name, driver, payment, notes))
    db.commit()
    return cur.lastrowid


def add_account(db, tenant_id, ident, proxy=None, exit_ip=None) -> int:
    cur = db.execute(
        "INSERT INTO accounts(tenant_id,seed,label,email,email_token,proxy,"
        "exit_ip,status,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
        (tenant_id, ident["seed"], ident.get("nama"), ident["email"],
         ident.get("email_token"), proxy, exit_ip, "pending", utcnow()))
    db.commit()
    return cur.lastrowid


def set_status(db, account_id, status, note=""):
    if status not in STATUSES:
        raise ValueError(f"Unknown status: {status}")
    db.execute("UPDATE accounts SET status=?,last_action=? WHERE id=?",
               (status, utcnow(), account_id))
    db.commit()
    log(db, account_id, "status", f"{status} {note}".strip())


def add_domain(db, account_id, fqdn, tld, expires_at=None, epp=None,
               ns1=None, ns2=None):
    db.execute(
        "INSERT INTO domains(account_id,fqdn,tld,registered_at,expires_at,"
        "epp,ns1,ns2) VALUES(?,?,?,?,?,?,?,?)",
        (account_id, fqdn, tld, utcnow(), expires_at, epp, ns1, ns2))
    db.commit()
    log(db, account_id, "domain_added", fqdn)


def ip_history(db, exit_ip, days=7):
    """Retrieve non-dead accounts recorded for an egress IP within N days."""
    cut = (datetime.datetime.now(datetime.timezone.utc)
           - datetime.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return db.execute(
        "SELECT id,email,status,created_at FROM accounts "
        "WHERE exit_ip=? AND created_at>? AND status!='dead' ORDER BY id",
        (exit_ip, cut)).fetchall()


def check_ip_budget(db, exit_ip, max_per_ip, days=7):
    """Verify IP usage threshold. Returns (allowed: bool, history: list)."""
    if not exit_ip:
        return True, []
    hist = ip_history(db, exit_ip, days)
    return len(hist) < max_per_ip, hist


def current_ip(timeout=12):
    """Detect current public IP without external third-party dependencies."""
    try:
        import urllib.request
        with urllib.request.urlopen("https://api.ipify.org", timeout=timeout) as r:
            ip = r.read().decode().strip()
        return ip if ip.count(".") == 3 else None
    except Exception:
        return None


def renew_queue(db, days_ahead=45):
    cut = (datetime.date.today() + datetime.timedelta(days=days_ahead)).isoformat()
    return db.execute(
        "SELECT d.fqdn, d.expires_at, a.email, a.id AS acc "
        "FROM domains d JOIN accounts a ON a.id=d.account_id "
        "WHERE d.status='active' AND (d.expires_at IS NULL OR d.expires_at<=?) "
        "ORDER BY d.expires_at IS NULL, d.expires_at", (cut,)).fetchall()


def counts(db) -> dict:
    q = lambda s: db.execute(s).fetchone()[0]
    return {
        "tenants": q("SELECT COUNT(*) FROM tenants"),
        "accounts": q("SELECT COUNT(*) FROM accounts"),
        "active": q("SELECT COUNT(*) FROM accounts WHERE status='active'"),
        "pending": q("SELECT COUNT(*) FROM accounts WHERE status='pending'"),
        "flagged": q("SELECT COUNT(*) FROM accounts WHERE status='flagged'"),
        "domains": q("SELECT COUNT(*) FROM domains WHERE status='active'"),
    }


def backup(db_path="sybil.db", outdir="backups", keep=7) -> str:
    os.makedirs(outdir, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    dst = os.path.join(outdir, f"sybil-{stamp}.db")
    src, out = sqlite3.connect(db_path), sqlite3.connect(dst)
    src.backup(out)
    out.close()
    src.close()
    olds = sorted(f for f in os.listdir(outdir) if f.startswith("sybil-"))
    for f in olds[:-keep]:
        os.remove(os.path.join(outdir, f))
    return dst
