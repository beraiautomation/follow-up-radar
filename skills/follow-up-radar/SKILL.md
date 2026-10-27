---
name: follow-up-radar
description: Find emails the user sent (quotes, invoices, meeting requests, questions) that never got a reply, and help draft follow-ups, using follow-up-radar. Read-only. Use when the user asks who they need to follow up with, which quotes or invoices went unanswered, or to chase leads that went quiet.
---

# Follow-up Radar

follow-up-radar reads a mailbox read-only and lists every thread where the user wrote last and
asked for something, with a draft follow-up for each. It never sends email.

## 1. Find or get the tool

Look for a folder with `radar/` in it. If there isn't one:

```bash
git clone https://github.com/beraiautomation/follow-up-radar
cd follow-up-radar
```

Python 3.9+ only, nothing to install. Use `python3` on macOS and Linux, `py` on Windows.

## 2. Run it

Try the demo first if the user is new to it: `python3 -m radar demo`

For their own mail, ask which provider they use.

- Gmail, iCloud, Yahoo, Fastmail: `python3 -m radar imap --email ADDRESS`
  It asks for an app password. **The user types it in their own terminal.** Never ask them to
  paste a password into the chat, and never write it to a file. If you must run it for them, they
  can set `FOLLOWUP_RADAR_PASSWORD` in their own shell first.
- Google Takeout export: `python3 -m radar mbox PATH --me ADDRESS`
- Folder of .eml files: `python3 -m radar eml PATH --me ADDRESS`
- Outlook and Hotmail over IMAP are not supported yet. Say so.
- If the user doesn't want a terminal at all and uses Gmail, point them to the no-install Gmail
  version: `gmail/SETUP.md` (paste one file into script.google.com, run `setup`).

Useful options: `--days`, `--wait`, `--ignore-domain` (their own company), `--name`,
`--model llama3.2` for local AI drafts with Ollama.

## 3. Go through the list with the user

Read `~/follow-up-radar/follow-ups.json` (or the `--out` folder).

- Lead with how many threads went quiet, then go through them in order: invoices and quotes first.
- For each one, say who, what was sent, and how long ago. Offer the draft, and adjust tone or
  details only from facts the user gives you or that are in their original email.
- Never add a price, discount, date or promise the user didn't state.
- Don't send anything. The user sends from their own email app ("Open in email" in the report).
- If a thread was clearly answered some other way (phone, text), tell the user to mark it done.
