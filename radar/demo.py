"""A made-up small business mailbox, so anyone can try the tool in seconds.

All names, addresses and domains here are invented (the .example domain is reserved
for examples and never belongs to a real company).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import format_datetime, make_msgid

from .parse import parse_bytes

OWNER = "sam@riverarepairs.example"
OWNER_NAME = "Sam Rivera"

_counter = [0]


def _mail(frm, to, subject, body, when, reply_to_id=None, refs=(), attach=None, headers=None):
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = frm, to, subject
    msg["Date"] = format_datetime(when)
    _counter[0] += 1
    msg["Message-ID"] = make_msgid(idstring=f"demo{_counter[0]}", domain="mail.example")
    if reply_to_id:
        msg["In-Reply-To"] = reply_to_id
        msg["References"] = " ".join([*refs, reply_to_id])
    for k, v in (headers or {}).items():
        msg[k] = v
    msg.set_content(body)
    if attach:
        msg.add_attachment(b"%PDF-1.4 demo", maintype="application", subtype="pdf", filename=attach)
    return msg


def demo_messages(now: datetime | None = None) -> list:
    now = now or datetime.now(timezone.utc)
    ago = lambda d, h=0: now - timedelta(days=d, hours=h)  # noqa: E731
    me = f"{OWNER_NAME} <{OWNER}>"
    raw = []

    # 1. Quote, no reply after 6 days.
    raw.append(_mail(me, "Maria Lopez <maria.lopez@gmail.com>", "Quote: bathroom tile repair",
                     "Hi Maria,\n\nThanks for having me over. The quote for re-tiling the shower wall and "
                     "fixing the grout is $1,450, including materials. I can start the week of the 18th.\n\n"
                     "Let me know if you'd like to go ahead.\n\nSam", ago(6)))

    # 2. Invoice, already followed up once, still nothing.
    first = _mail(me, "Delta Property Group <accounts@deltaprop.example>", "Invoice #1042 - unit 4B water heater",
                  "Hello,\n\nPlease find invoice #1042 for $860 attached, for the water heater replacement in unit 4B. "
                  "Payment is due within 14 days.\n\nThank you,\nSam", ago(16), attach="Invoice_1042.pdf")
    raw.append(first)
    raw.append(_mail(me, "Delta Property Group <accounts@deltaprop.example>", "Re: Invoice #1042 - unit 4B water heater",
                     "Hello,\n\nJust checking that you received invoice #1042. Could you let me know when payment is "
                     "planned?\n\nThanks,\nSam", ago(7), reply_to_id=first["Message-ID"]))

    # 3. Meeting request, no reply after 4 days.
    raw.append(_mail(me, "James Chen <jchen@outlook.com>", "Kitchen cabinet walkthrough",
                     "Hi James,\n\nAre you available for a quick walkthrough of the kitchen this week? "
                     "Thursday or Friday morning works for me.\n\nSam", ago(4)))

    # 4. Quote that got a reply: the customer answered, so the next step is yours, not a follow-up.
    q = _mail(me, "Priya Nair <priya.nair@gmail.com>", "Estimate for fence repair",
              "Hi Priya,\n\nThe estimate for replacing the six broken fence panels is $720. Any questions?\n\nSam", ago(9))
    raw.append(q)
    raw.append(_mail("Priya Nair <priya.nair@gmail.com>", me, "Re: Estimate for fence repair",
                     "Looks good! Can you do next Tuesday?", ago(8), reply_to_id=q["Message-ID"]))

    # 5. Question to a supplier, no reply after 5 days.
    raw.append(_mail(me, "Order Desk <orders@buildsupply.example>", "Deck boards order #5531",
                     "Hi,\n\nCan you confirm the delivery date for order #5531 (cedar deck boards)? "
                     "I need them on site by the 20th.\n\nThanks,\nSam", ago(5)))

    # 6. A thank-you note. Nothing to follow up on.
    raw.append(_mail(me, "Tom Becker <tom.becker@gmail.com>", "Thanks!",
                     "Thanks Tom, great working with you. Enjoy the new deck!\n\nSam", ago(6)))

    # 7. Quote sent yesterday. Too soon to chase.
    raw.append(_mail(me, "Lena Fischer <lena.f@gmail.com>", "Quote for gutter cleaning",
                     "Hi Lena,\n\nThe quote for cleaning and resealing the gutters is $380. Let me know!\n\nSam", ago(1)))

    # 8. Already followed up twice with no answer. Time to let it go.
    a1 = _mail(me, "Ana Costa <ana.costa@gmail.com>", "Proposal: basement waterproofing",
               "Hi Ana,\n\nHere is my proposal for the basement waterproofing. Let me know your thoughts.\n\nSam",
               ago(25), attach="Proposal_Basement.pdf")
    raw.append(a1)
    a2 = _mail(me, "Ana Costa <ana.costa@gmail.com>", "Re: Proposal: basement waterproofing",
               "Hi Ana, just checking in on the proposal. Any questions?\n\nSam", ago(15), reply_to_id=a1["Message-ID"])
    raw.append(a2)
    raw.append(_mail(me, "Ana Costa <ana.costa@gmail.com>", "Re: Proposal: basement waterproofing",
                     "Hi Ana, one last check on the waterproofing proposal. Let me know if the timing changes.\n\nSam",
                     ago(6), reply_to_id=a2["Message-ID"], refs=[a1["Message-ID"]]))

    # 9. Quote to a company. A colleague answered from the same company domain, so it counts as answered.
    b = _mail(me, "Lee Park <lee@harborcafe.example>", "Quote for patio lighting",
              "Hi Lee,\n\nThe quote for the patio lighting is $2,100. Let me know if you want to book it.\n\nSam", ago(10))
    raw.append(b)
    raw.append(_mail("Jo Kim <jo@harborcafe.example>", me, "Re: Quote for patio lighting",
                     "Hi Sam, Lee is away this week. We'd like to go ahead. When can you start?", ago(9),
                     reply_to_id=b["Message-ID"]))

    # 10. A proposal where only the attachment says what it is.
    raw.append(_mail(me, "Grace Obi <grace.obi@yahoo.com>", "Garage conversion",
                     "Hi Grace,\n\nAttached is what we talked about on Saturday.\n\nSam", ago(10),
                     attach="Proposal_Garage_Conversion.pdf"))

    # Some ordinary incoming mail and a newsletter, which the tool ignores.
    raw.append(_mail("Hardware Weekly <news@hardwareweekly.example>", me, "This week's deals",
                     "Save 20% on power tools.", ago(3), headers={"List-Unsubscribe": "<mailto:unsub@hardwareweekly.example>"}))
    raw.append(_mail("Maria Lopez <maria.lopez@gmail.com>", me, "Question about the old faucet",
                     "Hi Sam, unrelated question, do you also fix outdoor faucets?", ago(20)))

    owner = {OWNER}
    return [parse_bytes(m.as_bytes(), owner) for m in raw]
