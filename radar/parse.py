"""Turn raw email (RFC 822 bytes) into Message objects."""
from __future__ import annotations

import email
import html
import re
from datetime import timezone
from email import policy
from email.utils import parsedate_to_datetime

from .model import Message, addr, addrs, norm_id, split_ids

NOREPLY = re.compile(r"(no-?reply|do-?not-?reply|mailer-daemon|notifications?@|bounce)", re.I)


def _text_of(msg) -> str:
    """Best plain-text body, without quoted history."""
    part = None
    try:
        part = msg.get_body(preferencelist=("plain", "html"))
    except Exception:  # noqa: BLE001 - malformed mail
        part = None
    if part is None:
        return ""
    try:
        text = part.get_content()
    except Exception:  # noqa: BLE001
        payload = part.get_payload(decode=True) or b""
        text = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
    if part.get_content_type() == "text/html":
        text = re.sub(r"(?is)<(script|style).*?</\1>", " ", text)
        text = re.sub(r"(?i)<br\s*/?>|</p>|</div>", "\n", text)
        text = html.unescape(re.sub(r"<[^>]+>", " ", text))
    return strip_quoted(text)


QUOTE_START = re.compile(
    r"^(on .{3,120}wrote:|-{2,}\s*original message\s*-{2,}|from:\s.+|sent from my \w+|_{5,})\s*$",
    re.I,
)


def strip_quoted(text: str) -> str:
    """Keep only the new part of a message: drop '>' lines and the quoted thread below."""
    out = []
    for line in text.replace("\r\n", "\n").split("\n"):
        if QUOTE_START.match(line.strip()):
            break
        if line.lstrip().startswith(">"):
            continue
        out.append(line.rstrip())
    body = "\n".join(out).strip()
    return re.sub(r"\n{3,}", "\n\n", body)


def _is_auto(msg, sender: str) -> bool:
    if NOREPLY.search(sender or ""):
        return True
    if msg.get("List-Unsubscribe") or msg.get("List-Id"):
        return True
    if (msg.get("Precedence") or "").lower() in ("bulk", "list", "junk"):
        return True
    auto = (msg.get("Auto-Submitted") or "no").lower()
    return auto != "no" or bool(msg.get("X-Autoreply") or msg.get("X-Autorespond"))


def parse_bytes(raw: bytes, owner: set | None = None, sent_hint: bool | None = None) -> Message | None:
    msg = email.message_from_bytes(raw, policy=policy.default)
    return parse_message(msg, owner, sent_hint)


def parse_message(msg, owner: set | None = None, sent_hint: bool | None = None) -> Message | None:
    try:
        name, sender = addr(str(msg.get("From", "")))
    except Exception:  # noqa: BLE001
        return None
    try:
        date = parsedate_to_datetime(str(msg.get("Date"))) if msg.get("Date") else None
        if date is not None and date.tzinfo is None:
            date = date.replace(tzinfo=timezone.utc)
    except Exception:  # noqa: BLE001
        date = None
    owner = owner or set()
    labels = (msg.get("X-Gmail-Labels") or "").lower()
    if sent_hint is not None:
        is_sent = sent_hint
    elif labels:
        is_sent = "sent" in [x.strip() for x in labels.split(",")]
    else:
        is_sent = sender in owner
    attachments = [p.get_filename() for p in msg.iter_attachments() if p.get_filename()] if msg.is_multipart() else []
    return Message(
        message_id=norm_id(str(msg.get("Message-ID", ""))),
        subject=str(msg.get("Subject", "") or ""),
        sender=sender,
        sender_name=name,
        to=addrs(str(msg.get("To", "") or "")),
        cc=addrs(str(msg.get("Cc", "") or "")),
        date=date,
        in_reply_to=norm_id(str(msg.get("In-Reply-To", "") or "")),
        references=split_ids(str(msg.get("References", "") or "")),
        body=_text_of(msg)[:4000],
        attachments=attachments,
        is_sent=is_sent,
        auto=_is_auto(msg, sender),
    )
