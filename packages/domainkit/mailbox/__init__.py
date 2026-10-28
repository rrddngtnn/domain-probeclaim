"""domainkit.mailbox — antarmuka kotak masuk yang seragam.

Tiga implementasi, satu antarmuka, supaya driver tidak pernah tahu asal
emailnya:

    MockMailbox    in-memory, untuk test dan mock server lokal
    TempMailAPI    provider temp mail berbasis REST (konfigurasi, bukan
                   hardcode: base_url + bentuk respons)
    ImapCatchall   IMAP ke satu inbox catch-all dengan filter per `To:`

Yang wajib ada di tiap implementasi: `create()`, `messages()`, `wait_for()`.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field


@dataclass
class Message:
    id: str
    sender: str
    subject: str
    body: str
    received_at: str
    to: str = ""


@dataclass
class Mailbox:
    address: str
    token: str = ""
    expires_at: str | None = None
    meta: dict = field(default_factory=dict)


class MailboxBackend:
    """Kontrak. Turunan wajib mengimplementasikan ketiganya."""

    name = "backend"

    def create(self, seed: str, ttl_days: int = 30) -> Mailbox:
        raise NotImplementedError

    def messages(self, box: Mailbox, limit: int = 100) -> list[Message]:
        raise NotImplementedError

    def wait_for(self, box: Mailbox, pattern: str, since: str | None = None,
                 timeout: float = 120, poll: float = 3) -> tuple[str | None, Message | None]:
        """Polling sampai pola cocok. Return (match, message) atau (None, None)."""
        rx = re.compile(pattern)
        deadline, seen = time.time() + timeout, set()
        while time.time() < deadline:
            for m in self.messages(box):
                if m.id in seen:
                    continue
                seen.add(m.id)
                if since and m.received_at and m.received_at < since:
                    continue
                hay = f"{m.subject}\n{m.body}"
                hit = rx.search(hay)
                if hit:
                    return hit.group(1) if hit.groups() else hit.group(0), m
            time.sleep(poll)
        return None, None


class MockMailbox(MailboxBackend):
    """In-memory. Dipakai mock server dan test suite.

    `inject()` memungkinkan test menaruh pesan tanpa jaringan sama sekali.
    """

    name = "mock"

    def __init__(self):
        self._stores: dict[str, list[Message]] = {}
        self._seq = 0

    def create(self, seed: str, ttl_days: int = 30) -> Mailbox:
        # alamat harus unik per seed; seed panjang, jadi ambil hash-nya
        import hashlib
        h = hashlib.sha256(seed.encode()).hexdigest()[:14]
        addr = f"{h}@mock.test"
        self._stores.setdefault(addr, [])
        return Mailbox(address=addr, token=f"tok-{h[:8]}",
                       expires_at="2099-01-01T00:00:00Z")

    def inject(self, address: str, sender: str, subject: str, body: str,
               received_at: str | None = None) -> Message:
        self._seq += 1
        msg = Message(id=f"m{self._seq}", sender=sender, subject=subject,
                      body=body,
                      received_at=received_at or time.strftime(
                          "%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                      to=address)
        self._stores.setdefault(address, []).append(msg)
        return msg

    def messages(self, box: Mailbox, limit: int = 100) -> list[Message]:
        return list(self._stores.get(box.address, []))[-limit:]


class TempMailAPI(MailboxBackend):
    """Provider temp mail berbasis REST.

    Bentuk respons dikonfigurasi lewat `paths`, jadi kelas ini tidak
    mengandaikan satu vendor. Default meniru API yang umum:
        POST {base}{create_path}    -> {address, token}
        GET  {base}{list_path}      -> {messages: [...]}
        GET  {base}{detail_path}    -> {body, html}
    """

    name = "tempmail-api"

    def __init__(self, base_url: str, session=None, timeout: int = 25,
                 create_path="/api/inbox", list_path="/api/inbox/{address}/messages",
                 detail_path="/api/inbox/{address}/messages/{id}",
                 ttl_value="30d"):
        self.base = base_url.rstrip("/")
        self.s = session
        self.timeout = timeout
        self.create_path = create_path
        self.list_path = list_path
        self.detail_path = detail_path
        self.ttl_value = ttl_value

    def _session(self):
        if self.s is None:
            import requests
            self.s = requests.Session()
        return self.s

    def create(self, seed: str, ttl_days: int = 30) -> Mailbox:
        s = self._session()
        r = s.post(self.base + self.create_path,
                   json={"ttl": self.ttl_value}, timeout=self.timeout)
        r.raise_for_status()
        j = r.json()
        return Mailbox(address=j["address"], token=j.get("token", ""),
                       expires_at=j.get("expiresAt"), meta=j)

    def _auth(self, box: Mailbox):
        return {"Authorization": f"Bearer {box.token}"}

    def messages(self, box: Mailbox, limit: int = 100) -> list[Message]:
        s = self._session()
        url = self.base + self.list_path.format(address=box.address)
        r = s.get(url, headers=self._auth(box), params={"limit": limit},
                  timeout=self.timeout)
        r.raise_for_status()
        raw = r.json().get("messages", [])
        out = []
        for m in raw:
            body = m.get("snippet", "")
            if m.get("id"):
                try:
                    d = s.get(self.base + self.detail_path.format(
                        address=box.address, id=m["id"]),
                        headers=self._auth(box), timeout=self.timeout).json()
                    body = "\n".join(filter(None, (d.get("body"), d.get("html"))))
                    body = re.sub(r"<[^>]+>", " ", body)
                except Exception:
                    pass
            out.append(Message(
                id=str(m.get("id")), sender=m.get("from", ""),
                subject=m.get("subject", ""), body=body,
                received_at=m.get("receivedAt", ""), to=box.address))
        return out


class ImapCatchall(MailboxBackend):
    """IMAP ke satu inbox catch-all, filter per header `To:`.

    Alamat dibuat lokal (`seed@catchall_domain`) lalu dipakai untuk filter;
    kalau server meneruskan semua `*@domain` ke satu mailbox, ini bekerja
    tanpa membuat mailbox baru per identitas.
    """

    name = "imap-catchall"

    def __init__(self, host: str, user: str, password: str, domain: str,
                 port: int = 993, folder: str = "INBOX"):
        self.host, self.user = host, user
        self.password, self.domain = password, domain
        self.port, self.folder = port, folder

    def create(self, seed: str, ttl_days: int = 30) -> Mailbox:
        local = re.sub(r"[^a-z0-9]", "", seed.lower())[:20] or "box"
        return Mailbox(address=f"{local}@{self.domain}", token="",
                       meta={"kind": "catchall"})

    def messages(self, box: Mailbox, limit: int = 100) -> list[Message]:
        import email
        import imaplib
        from email.header import decode_header

        out = []
        with imaplib.IMAP4_SSL(self.host, self.port) as m:
            m.login(self.user, self.password)
            m.select(self.folder)
            _, data = m.search(None, "ALL")
            for uid in data[0].split()[-limit:]:
                _, raw = m.fetch(uid, "(RFC822)")
                msg = email.message_from_bytes(raw[0][1])
                to = str(msg.get("To", "")).lower()
                if box.address.lower() not in to:
                    continue
                body = ""
                if msg.is_multipart():
                    for p in msg.walk():
                        if p.get_content_type() == "text/plain":
                            body += p.get_payload(decode=True).decode(errors="ignore")
                else:
                    body = msg.get_payload(decode=True).decode(errors="ignore")
                subj = str(decode_header(str(msg.get("Subject", "")))[0][0])
                out.append(Message(id=uid.decode(), sender=str(msg.get("From", "")),
                                   subject=subj, body=body,
                                   received_at=str(msg.get("Date", "")), to=to))
        return out


def get_backend(name: str, **kw) -> MailboxBackend:
    """Factory. `mock` sengaja default supaya test tidak pernah ke jaringan."""
    return {"mock": MockMailbox,
            "tempmail-api": TempMailAPI,
            "imap-catchall": ImapCatchall}.get(name, MockMailbox)(**kw)
