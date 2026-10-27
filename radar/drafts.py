"""Write the follow-up drafts: plain templates by default, a local or API model if you ask."""
from __future__ import annotations

import json
import re
import urllib.request

from .analyze import Loop

TEMPLATES = {
    ("quote", 0): ("Just checking in on the {word} I sent on {date} ({topic}). "
                   "Do you have any questions, or would you like to go ahead?\n\n"
                   "Happy to change anything if it helps."),
    ("quote", 1): ("I haven't heard back about the {word} ({topic}), so I'll guess the timing isn't right for now. "
                   "If anything changes, just reply here and I'll pick it up."),
    ("invoice", 0): ("A friendly reminder about the invoice I sent on {date} ({topic}). "
                     "Could you let me know when payment is planned?\n\n"
                     "If you've already paid, thank you, and please ignore this."),
    ("invoice", 1): ("I'm following up again on the invoice I sent on {date} ({topic}). "
                     "Could you confirm a payment date this week? If there's a problem with the invoice, "
                     "tell me and I'll fix it."),
    ("meeting", 0): ("Following up on my email about \"{topic}\". "
                     "Would a quick call this week or next work for you?"),
    ("meeting", 1): ("One more try on \"{topic}\". If now isn't a good time, no problem. "
                     "Reply whenever it suits you and we'll find a time."),
    ("question", 0): ("Bringing this back to the top of your inbox: \"{topic}\". "
                      "When you get a moment, could you let me know?"),
    ("question", 1): ("Checking one last time about \"{topic}\". "
                      "If someone else should handle this, could you point me to them?"),
}


def _topic(subject: str, category: str = "") -> str:
    s = re.sub(r"^\s*((re|fw|fwd)\s*:\s*)+", "", subject or "", flags=re.I).strip()
    if category in ("quote", "invoice"):
        # "Quote: bathroom tile repair" -> "bathroom tile repair", "Invoice #1042 - ..." -> "#1042 - ..."
        stripped = re.sub(r"^(quote|quotation|estimate|proposal|invoice)\b\s*(for\b|:|-)?\s*", "", s, flags=re.I).strip()
        s = stripped or s
    return s or "my last email"


def template_draft(loop: Loop, signoff: str = "") -> str:
    step = min(loop.followups_sent, 1)
    body = TEMPLATES[(loop.category, step)].format(
        date=loop.first_sent.strftime("%b %d").replace(" 0", " "),
        topic=_topic(loop.subject, loop.category),
        word=loop.extra.get("word", "quote"),
    )
    hello = f"Hi {loop.first_name}," if loop.first_name else "Hi there,"
    end = "Thanks," + (f"\n{signoff}" if signoff else "")
    return f"{hello}\n\n{body}\n\n{end}"


# ---------------------------------------------------------------------------
# Optional: a model writes the draft. Any OpenAI-compatible endpoint works,
# including Ollama on your own computer (the default).
# ---------------------------------------------------------------------------

NUM = re.compile(r"\d+(?:[.,]\d+)*")


def _numbers(text: str) -> set:
    return {n.replace(",", "") for n in NUM.findall(text or "")}


def check_draft(draft: str, loop: Loop) -> str:
    """Return a problem, or '' if the draft is safe. A draft may not add numbers (prices, dates, amounts)."""
    allowed = _numbers(loop.snippet) | _numbers(loop.subject) | _numbers(loop.first_sent.strftime("%b %d %Y"))
    added = sorted(_numbers(draft) - allowed)
    if added:
        return "added numbers that aren't in your email: " + ", ".join(added)
    if len(draft.split()) > 140:
        return "too long"
    if re.search(r"\[(name|your name|date|company)\]", draft, re.I):
        return "left a placeholder in the text"
    return ""


PROMPT = """You write short, polite follow-up emails for a small business owner.
The customer did not reply to the email below. Write the follow-up email body only.

Rules:
- {step}
- Under 80 words. Plain, friendly, no pressure, no marketing language.
- Start with "Hi {first}," (or "Hi," if no name). End with "Thanks,"{sign}.
- Do NOT add any price, date, amount, or promise that is not in the original email.
- No subject line, no placeholders like [Name].

Original email (subject: {subject}), sent {days} days ago:
---
{snippet}
---"""


def model_draft(loop: Loop, model: str, url: str, signoff: str = "", api_key: str = "", timeout: int = 60) -> str:
    step = ("This is the first follow-up." if loop.followups_sent == 0
            else "This is the last follow-up. Say you'll stop asking, and they can reply any time.")
    prompt = PROMPT.format(step=step, first=loop.first_name or "", sign=f' then "{signoff}"' if signoff else "",
                           subject=loop.subject, days=loop.days_waiting, snippet=loop.snippet[:1500])
    payload = {"model": model, "temperature": 0.3, "messages": [{"role": "user", "content": prompt}]}
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST",
                                 headers={"Content-Type": "application/json",
                                          **({"Authorization": f"Bearer {api_key}"} if api_key else {})})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode())
    text = data["choices"][0]["message"]["content"].strip()
    return re.sub(r"^(subject:.*\n+)", "", text, flags=re.I).strip()


def write_drafts(loops: list, signoff: str = "", model: str = "", url: str = "", api_key: str = "") -> None:
    for loop in loops:
        loop.draft = template_draft(loop, signoff)
        loop.draft_source = "template"
        if not model:
            continue
        try:
            draft = model_draft(loop, model, url, signoff, api_key)
        except Exception as exc:  # noqa: BLE001 - fall back to the template
            loop.draft_note = f"model failed ({type(exc).__name__}), used the template"
            continue
        problem = check_draft(draft, loop)
        if problem:
            loop.draft_note = f"model draft rejected: {problem}. Used the template."
        else:
            loop.draft, loop.draft_source = draft, model
