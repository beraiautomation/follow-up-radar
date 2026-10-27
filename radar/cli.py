"""Command line: python -m radar <demo|imap|mbox|eml>"""
from __future__ import annotations

import argparse
import getpass
import os
import sys
import webbrowser
from pathlib import Path

from . import __version__
from .analyze import find_loops, guess_owner_name
from .demo import OWNER, demo_messages
from .drafts import write_drafts
from .report import write_outputs
from .sources import from_eml_folder, from_imap, from_mbox, guess_host

DEFAULT_OUT = Path.home() / "follow-up-radar"
OLLAMA_URL = "http://localhost:11434/v1/chat/completions"


def _common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--days", type=int, default=30, help="look back this many days (default 30)")
    p.add_argument("--wait", type=int, default=3, help="days without a reply before it shows up (default 3)")
    p.add_argument("--max-followups", type=int, default=2, help="stop suggesting after this many follow-ups (default 2)")
    p.add_argument("--ignore-domain", action="append", default=[], help="skip a domain, e.g. your own team's (repeatable)")
    p.add_argument("--name", default="", help="your name for the sign-off (default: from your sent mail)")
    p.add_argument("--model", default="", help="write drafts with a model, e.g. llama3.2 (Ollama). Default: templates")
    p.add_argument("--model-url", default=OLLAMA_URL, help=f"OpenAI-compatible chat URL (default {OLLAMA_URL})")
    p.add_argument("--out", default=str(DEFAULT_OUT), help=f"where to save the report (default {DEFAULT_OUT})")
    p.add_argument("--no-open", action="store_true", help="don't open the report in your browser")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m radar",
                                description="Find emails that never got a reply, and draft the follow-up. Read-only.")
    p.add_argument("--version", action="version", version=f"follow-up-radar {__version__}")
    sub = p.add_subparsers(dest="source", required=True)

    d = sub.add_parser("demo", help="try it on a made-up small business mailbox")
    _common(d)

    i = sub.add_parser("imap", help="read your mailbox over IMAP (Gmail, iCloud, Yahoo, Fastmail...)")
    i.add_argument("--email", required=True, help="your email address")
    i.add_argument("--host", default="", help="IMAP server (guessed from your address)")
    _common(i)

    m = sub.add_parser("mbox", help="read an .mbox export, e.g. from Google Takeout")
    m.add_argument("path")
    m.add_argument("--me", action="append", required=True, help="your email address (repeatable)")
    _common(m)

    e = sub.add_parser("eml", help="read a folder of .eml files")
    e.add_argument("path")
    e.add_argument("--me", action="append", required=True, help="your email address (repeatable)")
    _common(e)
    return p


def run(args) -> int:
    if args.source == "demo":
        owner, messages, source = {OWNER}, demo_messages(), "the demo mailbox (made-up data)"
    elif args.source == "imap":
        owner = {args.email.lower()}
        password = os.environ.get("FOLLOWUP_RADAR_PASSWORD") or getpass.getpass(
            f"App password for {args.email} (not saved anywhere): ")
        host = args.host or guess_host(args.email)
        print(f"Reading {args.email} on {host}, read-only...")
        messages = from_imap(args.email, password, host, args.days)
        source = f"{args.email} over IMAP"
    elif args.source == "mbox":
        owner = {a.lower() for a in args.me}
        messages, source = from_mbox(Path(args.path).expanduser(), owner), Path(args.path).name
    else:
        owner = {a.lower() for a in args.me}
        messages, source = from_eml_folder(Path(args.path).expanduser(), owner), Path(args.path).name

    loops, stats = find_loops(messages, owner, wait_days=args.wait, lookback_days=args.days,
                              max_followups=args.max_followups, ignore_domains=set(args.ignore_domain))
    full_name = args.name or guess_owner_name(messages, owner)
    signoff = full_name.split(" ")[0] if full_name else ""
    write_drafts(loops, signoff, args.model, args.model_url, os.environ.get("FOLLOWUP_RADAR_API_KEY", ""))
    page = write_outputs(loops, stats, source, Path(args.out).expanduser())

    print(f"\n{len(loops)} conversation(s) went quiet. Checked {stats['threads']} threads in {len(messages)} emails.")
    for lp in loops:
        print(f"  - {lp.contact_name or lp.contact_email}: {lp.subject}  ({lp.category_label}, {lp.days_waiting} days)")
    print(f"\nReport: {page}")
    if not args.no_open:
        webbrowser.open(page.resolve().as_uri())
    return 0


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
    args = build_parser().parse_args(argv)
    try:
        return run(args)
    except KeyboardInterrupt:
        print("\nStopped.")
        return 130
