"""Read email from IMAP (read-only), an .mbox export, or a folder of .eml files."""
from __future__ import annotations

import imaplib
import mailbox
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .model import domain
from .parse import parse_bytes

IMAP_HOSTS = {
    "gmail.com": "imap.gmail.com", "googlemail.com": "imap.gmail.com",
    "icloud.com": "imap.mail.me.com", "me.com": "imap.mail.me.com", "mac.com": "imap.mail.me.com",
    "yahoo.com": "imap.mail.yahoo.com", "aol.com": "imap.aol.com",
    "fastmail.com": "imap.fastmail.com", "zoho.com": "imap.zoho.com", "gmx.com": "imap.gmx.com",
}


def guess_host(address: str) -> str:
    d = domain(address)
    return IMAP_HOSTS.get(d, f"imap.{d}")


def _folders(conn) -> list:
    """Return [(flags, name)] for every folder."""
    typ, data = conn.list()
    out = []
    for raw in data or []:
        line = raw.decode(errors="replace") if isinstance(raw, bytes) else str(raw)
        m = re.match(r'\((?P<flags>[^)]*)\)\s+(?:"[^"]*"|NIL)\s+(?P<name>.+)$', line)
        if m:
            out.append((m.group("flags").lower(), m.group("name").strip()))
    return out


def pick_folders(folders: list) -> tuple:
    """Find the Sent folder and the folders where replies land."""
    sent = next((n for f, n in folders if "\\sent" in f), None)
    if sent is None:
        sent = next((n for f, n in folders if re.search(r"sent", n, re.I)), None)
    every = next((n for f, n in folders if "\\all" in f), None)
    inbox = next((n for f, n in folders if n.strip('"').upper() == "INBOX"), '"INBOX"')
    archive = next((n for f, n in folders if "\\archive" in f), None)
    reply_folders = [every] if every else [inbox] + ([archive] if archive else [])
    return sent, reply_folders


def _fetch(conn, folder: str, since: datetime, owner: set, sent_hint: bool, headers_only: bool) -> list:
    typ, _ = conn.select(folder, readonly=True)  # read-only: nothing is marked as read or changed
    if typ != "OK":
        return []
    typ, data = conn.search(None, "SINCE", since.strftime("%d-%b-%Y"))
    ids = (data[0] or b"").split() if data else []
    part = "BODY.PEEK[HEADER]" if headers_only else "BODY.PEEK[]"
    out = []
    for i in range(0, len(ids), 50):
        chunk = b",".join(ids[i:i + 50])
        typ, rows = conn.fetch(chunk, f"({part})")
        for row in rows or []:
            if isinstance(row, tuple) and len(row) >= 2:
                msg = parse_bytes(row[1], owner, sent_hint)
                if msg:
                    out.append(msg)
    return out


def from_imap(email_address: str, password: str, host: str = "", days: int = 30, connect=None) -> list:
    owner = {email_address.lower()}
    since = datetime.now(timezone.utc) - timedelta(days=days * 2)
    conn = (connect or imaplib.IMAP4_SSL)(host or guess_host(email_address))
    try:
        conn.login(email_address, password)
        sent, reply_folders = pick_folders(_folders(conn))
        if not sent:
            raise SystemExit("Couldn't find your Sent folder.")
        messages = _fetch(conn, sent, since, owner, True, headers_only=False)
        for folder in reply_folders:
            for m in _fetch(conn, folder, since, owner, None, headers_only=True):
                if m.sender not in owner:
                    m.is_sent = False
                    messages.append(m)
    finally:
        try:
            conn.logout()
        except Exception:  # noqa: BLE001
            pass
    return messages


def from_mbox(path: Path, owner: set) -> list:
    box = mailbox.mbox(str(path), create=False)
    out = []
    try:
        for raw in box:
            msg = parse_bytes(raw.as_bytes(), owner)
            if msg:
                out.append(msg)
    finally:
        box.close()
    return out


def from_eml_folder(path: Path, owner: set) -> list:
    out = []
    for f in sorted(Path(path).rglob("*.eml")):
        msg = parse_bytes(f.read_bytes(), owner)
        if msg:
            out.append(msg)
    return out
