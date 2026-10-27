"""Tests for follow-up-radar. Run: python -m unittest discover -s tests -v"""
import json
import mailbox
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import format_datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from radar.analyze import classify, find_loops  # noqa: E402
from radar.demo import OWNER, demo_messages  # noqa: E402
from radar.drafts import check_draft, template_draft, write_drafts  # noqa: E402
from radar.parse import parse_bytes, strip_quoted  # noqa: E402
from radar.report import render  # noqa: E402
from radar.sources import from_eml_folder, from_imap, from_mbox, pick_folders  # noqa: E402

NOW = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
ME = "me@shop.example"


def mail(frm, to, subject, body, days_ago, msg_id, reply_to=None, headers=None, attach=None):
    m = EmailMessage()
    m["From"], m["To"], m["Subject"] = frm, to, subject
    m["Date"] = format_datetime(NOW - timedelta(days=days_ago))
    m["Message-ID"] = f"<{msg_id}@test>"
    if reply_to:
        m["In-Reply-To"] = f"<{reply_to}@test>"
        m["References"] = f"<{reply_to}@test>"
    for k, v in (headers or {}).items():
        m[k] = v
    m.set_content(body)
    if attach:
        m.add_attachment(b"x", maintype="application", subtype="pdf", filename=attach)
    return m


def loops_for(raw, **kw):
    msgs = [parse_bytes(m.as_bytes(), {ME}) for m in raw]
    return find_loops(msgs, {ME}, now=NOW, **kw)


class Demo(unittest.TestCase):
    def test_demo_finds_exactly_the_five_quiet_threads(self):
        loops, stats = find_loops(demo_messages(NOW), {OWNER}, now=NOW)
        found = sorted(lp.contact_email for lp in loops)
        self.assertEqual(found, sorted([
            "grace.obi@yahoo.com", "accounts@deltaprop.example", "maria.lopez@gmail.com",
            "jchen@outlook.com", "orders@buildsupply.example"]))
        self.assertEqual(stats["answered"], 2)      # Priya replied, and Lee's colleague replied
        self.assertEqual(stats["not_an_ask"], 1)    # the thank-you note
        self.assertEqual(stats["too_recent"], 1)    # yesterday's quote
        self.assertEqual(stats["gave_up"], 1)       # Ana, already followed up twice

    def test_most_important_first(self):
        loops, _ = find_loops(demo_messages(NOW), {OWNER}, now=NOW)
        self.assertEqual([lp.priority for lp in loops], sorted([lp.priority for lp in loops], reverse=True))


class Threads(unittest.TestCase):
    def test_reply_by_subject_without_headers_counts(self):
        raw = [mail(ME, "a@x.example", "Quote for roof", "The quote is $900. Let me know.", 6, "q1"),
               mail("a@x.example", ME, "RE: Quote for roof", "Yes please", 5, "r1")]
        loops, stats = loops_for(raw)
        self.assertEqual(loops, [])
        self.assertEqual(stats["answered"], 1)

    def test_reply_with_new_subject_from_same_person_counts(self):
        raw = [mail(ME, "a@gmail.com", "Quote for roof", "The quote is $900. Let me know.", 6, "q1"),
               mail("a@gmail.com", ME, "question", "When can you start?", 5, "r1")]
        self.assertEqual(loops_for(raw)[0], [])

    def test_stranger_on_same_free_domain_is_not_a_reply(self):
        raw = [mail(ME, "a@gmail.com", "Quote for roof", "The quote is $900. Let me know.", 6, "q1"),
               mail("someone.else@gmail.com", ME, "hi", "unrelated", 5, "r1")]
        self.assertEqual(len(loops_for(raw)[0]), 1)

    def test_old_reply_then_new_question_is_open(self):
        raw = [mail(ME, "a@x.example", "Deck", "Can you send the measurements?", 10, "m1"),
               mail("a@x.example", ME, "Re: Deck", "Here they are.", 9, "m2", reply_to="m1"),
               mail(ME, "a@x.example", "Re: Deck", "Thanks! The quote is $2,000. Shall I book it?", 6, "m3", reply_to="m2")]
        loops, _ = loops_for(raw)
        self.assertEqual(len(loops), 1)
        self.assertEqual(loops[0].category, "quote")
        self.assertEqual(loops[0].followups_sent, 0)

    def test_newsletters_and_noreply_are_ignored(self):
        raw = [mail(ME, "noreply@service.example", "Quote request", "Can you send a quote?", 6, "n1"),
               mail(ME, "list@x.example", "Question", "Any update?", 6, "n2", headers={"List-Id": "<x>"})]
        self.assertEqual(loops_for(raw)[0], [])

    def test_ignore_domain(self):
        raw = [mail(ME, "boss@shop.example", "Invoice check", "Can you approve the invoice?", 6, "i1")]
        self.assertEqual(loops_for(raw, ignore_domains={"shop.example"})[0], [])

    def test_wait_and_max_followups(self):
        raw = [mail(ME, "a@x.example", "Quote", "Quote attached. Let me know.", 2, "w1")]
        self.assertEqual(loops_for(raw, wait_days=3)[0], [])
        self.assertEqual(len(loops_for(raw, wait_days=1)[0]), 1)


class Classify(unittest.TestCase):
    def parse(self, subject, body, attach=None):
        return parse_bytes(mail(ME, "a@x.example", subject, body, 5, "c1", attach=attach).as_bytes(), {ME})

    def test_categories(self):
        self.assertEqual(classify(self.parse("Invoice 12", "Invoice attached, due in 14 days."))[0], "invoice")
        self.assertEqual(classify(self.parse("Hello", "Are you free for a call on Monday?"))[0], "meeting")
        self.assertEqual(classify(self.parse("Docs", "Here you go.", attach="Proposal_v2.pdf"))[0], "quote")
        self.assertEqual(classify(self.parse("Docs", "Here you go.", attach="Proposal_v2.pdf"))[4], "proposal")

    def test_thanks_and_fyi_are_not_asks(self):
        self.assertIsNone(classify(self.parse("Thanks!", "Thanks, great working with you.")))
        self.assertIsNone(classify(self.parse("FYI", "Sharing the photos from today.")))

    def test_quoted_history_is_ignored(self):
        text = "Sounds good.\n\nOn Mon, Oct 5, 2026 at 9:00 Bob wrote:\n> Can you send the invoice?\n> Thanks"
        self.assertEqual(strip_quoted(text), "Sounds good.")


class Drafts(unittest.TestCase):
    def setUp(self):
        self.loops, _ = find_loops(demo_messages(NOW), {OWNER}, now=NOW)

    def test_templates_greet_people_not_companies(self):
        by = {lp.contact_email: template_draft(lp, "Sam") for lp in self.loops}
        self.assertTrue(by["maria.lopez@gmail.com"].startswith("Hi Maria,"))
        self.assertTrue(by["accounts@deltaprop.example"].startswith("Hi there,"))
        self.assertTrue(by["orders@buildsupply.example"].startswith("Hi there,"))
        self.assertIn("proposal", by["grace.obi@yahoo.com"])
        for d in by.values():
            self.assertTrue(d.rstrip().endswith("Thanks,\nSam"))
            self.assertEqual(check_draft(d, next(lp for lp in self.loops if template_draft(lp, "Sam") == d)), "")

    def test_number_guard(self):
        lp = next(lp for lp in self.loops if lp.contact_email == "maria.lopez@gmail.com")
        self.assertEqual(check_draft("Hi Maria, any update on the $1,450 quote?", lp), "")
        self.assertIn("1200", check_draft("Hi Maria, I can do it for $1,200 if you book now.", lp))
        self.assertIn("placeholder", check_draft("Hi [Name], any update?", lp))

    def test_model_drafts_are_checked(self):
        replies = iter([
            "Hi Grace,\n\nJust checking in on the garage proposal. Any questions?\n\nThanks,\nSam",
            "Hi there,\n\nPlease pay the $999 late fee by Friday.\n\nThanks,\nSam",
        ])

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                self.rfile.read(int(self.headers["Content-Length"]))
                body = json.dumps({"choices": [{"message": {"content": next(replies)}}]}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        server = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            two = self.loops[:2]
            write_drafts(two, "Sam", model="fake", url=f"http://127.0.0.1:{server.server_port}/v1/chat/completions")
        finally:
            server.shutdown()
            server.server_close()
        self.assertEqual(two[0].draft_source, "fake")
        self.assertEqual(two[1].draft_source, "template")
        self.assertIn("999", two[1].draft_note)

    def test_model_down_falls_back(self):
        lp = self.loops[:1]
        write_drafts(lp, "Sam", model="x", url="http://127.0.0.1:9/v1/chat/completions")
        self.assertEqual(lp[0].draft_source, "template")
        self.assertIn("model failed", lp[0].draft_note)


class FakeIMAP:
    """Stands in for imaplib.IMAP4_SSL and records that nothing was changed."""

    def __init__(self, host):
        self.host, self.selected, self.readonly = host, None, []
        raw = [mail(ME, "a@gmail.com", "Quote", "The quote is $500. Let me know.", 6, "s1"),
               mail(ME, "b@gmail.com", "Estimate", "Estimate attached. Any questions?", 6, "s2"),
               mail("b@gmail.com", ME, "Re: Estimate", "Go ahead!", 5, "r2", reply_to="s2")]
        self.boxes = {'"[Gmail]/Sent Mail"': [raw[0].as_bytes(), raw[1].as_bytes()],
                      '"[Gmail]/All Mail"': [m.as_bytes() for m in raw]}

    def login(self, user, pw):
        self.user = user

    def list(self):
        return "OK", [b'(\\HasNoChildren) "/" "INBOX"', b'(\\All \\HasNoChildren) "/" "[Gmail]/All Mail"',
                      b'(\\HasNoChildren \\Sent) "/" "[Gmail]/Sent Mail"']

    def select(self, name, readonly=False):
        self.selected = name
        self.readonly.append(readonly)
        return "OK", [b"1"]

    def search(self, charset, *criteria):
        return "OK", [" ".join(str(i + 1) for i in range(len(self.boxes[self.selected]))).encode()]

    def fetch(self, ids, what):
        assert "PEEK" in what, "must not mark mail as read"
        rows = []
        for i in ids.split(b","):
            rows.append((b"x", self.boxes[self.selected][int(i) - 1]))
        return "OK", rows

    def logout(self):
        pass


class Sources(unittest.TestCase):
    def test_imap_is_read_only_and_finds_the_open_quote(self):
        holder = {}

        def connect(host):
            holder["c"] = FakeIMAP(host)
            return holder["c"]

        msgs = from_imap(ME, "pw", host="imap.test", days=30, connect=connect)
        self.assertTrue(all(holder["c"].readonly))
        loops, _ = find_loops(msgs, {ME}, now=NOW)
        self.assertEqual([lp.contact_email for lp in loops], ["a@gmail.com"])

    def test_pick_folders_fallbacks(self):
        sent, reply = pick_folders([("\\hasnochildren", "INBOX"), ("\\hasnochildren", '"Sent Items"')])
        self.assertEqual(sent, '"Sent Items"')
        self.assertEqual(reply, ["INBOX"])

    def test_mbox_with_gmail_labels_and_eml_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            q = mail(ME, "a@gmail.com", "Quote", "The quote is $500. Let me know.", 6, "s1",
                     headers={"X-Gmail-Labels": "Sent,Important"})
            box = mailbox.mbox(str(Path(tmp) / "all.mbox"))
            box.add(q)
            box.flush()
            box.close()
            msgs = from_mbox(Path(tmp) / "all.mbox", {ME})
            self.assertTrue(msgs[0].is_sent)
            (Path(tmp) / "a.eml").write_bytes(q.as_bytes())
            self.assertEqual(len(find_loops(from_eml_folder(Path(tmp), {ME}), {ME}, now=NOW)[0]), 1)


class Report(unittest.TestCase):
    def test_render_escapes_and_lists(self):
        loops, stats = find_loops(demo_messages(NOW), {OWNER}, now=NOW)
        write_drafts(loops, "Sam")
        loops[0].contact_name = "<script>x</script>"
        html = render(loops, stats, "demo", NOW)
        self.assertNotIn("<script>x</script>", html)
        self.assertIn("5</b> conversations went quiet", html)
        self.assertIn("Open in email", html)

    def test_empty_state(self):
        self.assertIn("All clear", render([], {"threads": 0}, "demo", NOW))


if __name__ == "__main__":
    unittest.main()
