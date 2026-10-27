"""The small data model everything else works with."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from email.utils import getaddresses, parseaddr


@dataclass
class Message:
    message_id: str
    subject: str
    sender: str                 # email address, lower case
    sender_name: str
    to: list = field(default_factory=list)      # list of (name, address)
    cc: list = field(default_factory=list)
    date: datetime | None = None
    in_reply_to: str = ""
    references: list = field(default_factory=list)
    body: str = ""
    attachments: list = field(default_factory=list)
    is_sent: bool = False       # sent by the owner of the mailbox
    auto: bool = False          # newsletters, auto-replies, bulk mail

    @property
    def thread_ids(self) -> set:
        ids = set(self.references)
        if self.in_reply_to:
            ids.add(self.in_reply_to)
        return ids


def norm_id(value: str) -> str:
    value = (value or "").strip()
    m = re.search(r"<[^>]+>", value)
    return (m.group(0) if m else value).lower()


def split_ids(value: str) -> list:
    return [x.lower() for x in re.findall(r"<[^>]+>", value or "")]


def addr(value: str) -> tuple:
    name, address = parseaddr(value or "")
    return name.strip().strip('"'), address.strip().lower()


def addrs(*values: str) -> list:
    out = []
    for name, address in getaddresses([v for v in values if v]):
        if address:
            out.append((name.strip().strip('"'), address.strip().lower()))
    return out


SUBJECT_PREFIX = re.compile(r"^\s*((re|fw|fwd|aw|sv|antw|tr)\s*(\[\d+\])?\s*:\s*)+", re.I)


def clean_subject(subject: str) -> str:
    s = SUBJECT_PREFIX.sub("", subject or "").strip()
    return re.sub(r"\s+", " ", s).lower()


def domain(address: str) -> str:
    return address.rsplit("@", 1)[-1].lower() if "@" in address else ""
