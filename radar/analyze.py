"""Find the conversations that went quiet and need a follow-up."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from .model import Message, clean_subject, domain

FREEMAIL = {
    "gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "live.com", "msn.com", "yahoo.com",
    "icloud.com", "me.com", "mac.com", "aol.com", "proton.me", "protonmail.com", "gmx.com", "mail.com",
    "zoho.com", "yandex.com", "fastmail.com", "hey.com",
}

CATEGORIES = [
    # (name, label, priority, pattern)
    ("quote", "Quote or proposal", 3, r"\b(quote|quotation|estimate|proposal|pricing|price list|bid|scope of work|sow)\b"),
    ("invoice", "Invoice or payment", 3, r"\b(invoice|payment|balance due|overdue|amount due|outstanding balance|remittance)\b"),
    ("meeting", "Meeting or call", 2, r"\b(meet|meeting|call|schedule|availability|available|calendar|book a time|zoom|teams link|demo)\b"),
    ("question", "Waiting on an answer", 1, r"\b(let me know|get back to me|your thoughts|can you confirm|please confirm|could you confirm|approve|approval|sign off|sign the|any questions)\b"),
]
GENERIC_NAME = re.compile(r"\b(group|desk|team|inc|llc|ltd|gmbh|co|company|corp|accounts?|billing|support|sales|"
                          r"office|orders?|info|admin|reception|services?|department|dept|hr|payables?)\b", re.I)
GENERIC_LOCAL = re.compile(r"^(accounts?|accounting|ap|ar|billing|orders?|info|sales|support|office|admin|hello|"
                           r"contact|team|hr|payables?|invoices?|bookings?|enquiries|inquiries)$")
ATTACH_HINT = re.compile(r"(quote|proposal|estimate|invoice|contract|agreement|sow)", re.I)
JUST_THANKS = re.compile(r"^\W*(thanks|thank you|thx|cheers|got it|sounds good|great|perfect|ok|okay|will do|noted)\b", re.I)


@dataclass
class Loop:
    contact_name: str
    contact_email: str
    subject: str
    category: str
    category_label: str
    priority: int
    reasons: list
    first_sent: datetime
    last_sent: datetime
    days_waiting: int
    followups_sent: int
    snippet: str
    message_id: str
    draft: str = ""
    draft_source: str = "template"
    draft_note: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def first_name(self) -> str:
        """First name for the greeting, or '' for teams, companies and shared inboxes."""
        name = (self.contact_name or "").strip()
        local = self.contact_email.split("@")[0].lower()
        if not name or "@" in name or GENERIC_NAME.search(name) or GENERIC_LOCAL.match(local):
            return ""
        first = re.split(r"[\s,]+", name)[0]
        return first[:1].upper() + first[1:]


def classify(msg: Message) -> tuple:
    """Return (category, label, priority, reasons) for a sent email, or None if it doesn't ask for anything."""
    text = f"{msg.subject}\n{msg.body}"
    low = text.lower()
    reasons = []
    hits = []
    for name, label, prio, pat in CATEGORIES:
        m = re.search(pat, low)
        if m:
            hits.append((name, label, prio))
            reasons.append(f'mentions "{m.group(0)}"')
    files = [f for f in msg.attachments if ATTACH_HINT.search(f or "")]
    if files:
        reasons.append("attached " + ", ".join(files[:2]))
        if not hits:
            hits.append(("quote", "Quote or proposal", 3))
    asks = "?" in msg.body
    if asks:
        reasons.append("asks a question")
    if not hits and not asks:
        return None
    body = msg.body.strip()
    if JUST_THANKS.match(body) and len(body) < 120 and not files and not asks:
        return None
    word = "quote"
    found = re.findall(r"\b(proposal|estimate|quote|quotation|scope of work|sow)\b", low + " " + re.sub(r"[_.-]", " ", " ".join(files).lower()))
    if found:
        word = {"quotation": "quote", "scope of work": "proposal", "sow": "proposal"}.get(found[0], found[0])
    reasons_word = word
    if hits:
        name, label, prio = max(hits, key=lambda h: h[2])
    else:
        name, label, prio = "question", "Waiting on an answer", 1
    return name, label, prio, reasons, reasons_word


def _related(sender: str, contacts: set) -> bool:
    if sender in contacts:
        return True
    d = domain(sender)
    return bool(d) and d not in FREEMAIL and any(domain(c) == d for c in contacts)


def find_loops(messages: list, owner: set, now: datetime | None = None, wait_days: int = 3,
               lookback_days: int = 30, max_followups: int = 2, ignore_domains: set | None = None) -> tuple:
    """Return (loops, stats). A loop is a thread where you wrote last and nobody answered."""
    now = now or datetime.now(timezone.utc)
    ignore = {d.lower().lstrip("@") for d in (ignore_domains or set())}
    owner = {o.lower() for o in owner}
    since = now - timedelta(days=lookback_days)
    msgs = sorted([m for m in messages if m.date], key=lambda m: m.date)

    incoming = [m for m in msgs if not m.is_sent and m.sender not in owner and not m.auto]
    stats = {"sent_scanned": 0, "threads": 0, "answered": 0, "not_an_ask": 0, "too_recent": 0,
             "gave_up": 0, "found": 0}

    loops: list = []
    # Group your sent emails into threads: same cleaned subject and same main contact.
    threads: dict = {}
    for m in msgs:
        if not m.is_sent or m.auto or m.date < since - timedelta(days=lookback_days):
            continue
        contacts = [(n, a) for n, a in m.to if a not in owner and domain(a) not in ignore
                    and not re.search(r"no-?reply|do-?not-?reply", a)]
        if not contacts:
            continue
        key = (clean_subject(m.subject), contacts[0][1])
        threads.setdefault(key, []).append((m, contacts))

    for (subj, main), items in threads.items():
        mine = [m for m, _ in items]
        last = mine[-1]
        if last.date < since:
            continue
        stats["threads"] += 1
        stats["sent_scanned"] += len(mine)
        contact_addrs = {a for _, cs in items for _, a in cs}
        ids = {m.message_id for m in mine if m.message_id}

        def is_reply(r: Message) -> bool:
            if not _related(r.sender, contact_addrs):
                return False
            if r.thread_ids & ids:
                return True
            if clean_subject(r.subject) == subj:
                return True
            return r.sender in contact_addrs  # they wrote back, even with a new subject

        replies = [r for r in incoming if r.date > mine[0].date and is_reply(r)]
        last_reply = replies[-1].date if replies else None
        if last_reply and last_reply >= last.date:
            stats["answered"] += 1
            continue
        streak = [m for m in mine if not last_reply or m.date > last_reply]
        ask = streak[0]
        verdict = classify(ask)
        if verdict is None:
            stats["not_an_ask"] += 1
            continue
        days = (now - last.date).days
        if days < wait_days:
            stats["too_recent"] += 1
            continue
        followups = len(streak) - 1
        if followups >= max_followups:
            stats["gave_up"] += 1
            continue
        cat, label, prio, reasons, word = verdict
        name = next((n for _, cs in items for n, a in cs if a == main and n), "")
        stats["found"] += 1
        loops.append(Loop(
            contact_name=name, contact_email=main, subject=ask.subject, category=cat,
            category_label=label, priority=prio, reasons=reasons, first_sent=ask.date,
            last_sent=last.date, days_waiting=days, followups_sent=followups,
            snippet=ask.body[:600], message_id=last.message_id, extra={"word": word},
        ))

    loops.sort(key=lambda lp: (-lp.priority, -lp.days_waiting))
    return loops, stats


def guess_owner_name(messages: list, owner: set) -> str:
    for m in messages:
        if m.sender in owner and m.sender_name:
            return m.sender_name
    return ""
