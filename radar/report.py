"""The report: one page with every quiet conversation and a ready draft."""
from __future__ import annotations

import csv
import json
from datetime import datetime
from html import escape
from pathlib import Path

REPO_URL = "https://github.com/beraiautomation/follow-up-radar"

CSS = """
:root{--bg:#f7f6f3;--card:#fff;--ink:#1c1b22;--muted:#6b6878;--line:#e6e3ec;--accent:#6d28d9;--accent2:#db2777;
--hi:#d93a52;--hi-bg:#fdecef;--mid:#b7791f;--mid-bg:#fdf3e1;--lo:#2563eb;--lo-bg:#e8effd;--ok:#0f9f6e}
@media (prefers-color-scheme:dark){:root{--bg:#121117;--card:#1b1a22;--ink:#f1eff7;--muted:#a19dae;--line:#2c2a36;
--accent:#a78bfa;--accent2:#f472b6;--hi:#fb7185;--hi-bg:#33161d;--mid:#fbbf24;--mid-bg:#2f2410;--lo:#93b4fd;--lo-bg:#16213a;--ok:#34d399}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:860px;margin:0 auto;padding:40px 20px 70px}
.kick{font-size:12px;letter-spacing:.16em;text-transform:uppercase;color:var(--muted);font-weight:600}
h1{font-size:34px;line-height:1.1;margin:6px 0 6px;letter-spacing:-.02em}
h1 b{background:linear-gradient(90deg,var(--accent),var(--accent2));-webkit-background-clip:text;background-clip:text;color:transparent}
.sub{color:var(--muted);margin:0 0 22px}
.stats{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 26px}
.stat{background:var(--card);border:1px solid var(--line);border-radius:999px;padding:5px 12px;font-size:13px;color:var(--muted)}
.stat b{color:var(--ink)}
.card{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:18px 20px;margin:0 0 14px;transition:opacity .2s}
.card.done{opacity:.45}
.top{display:flex;gap:10px;align-items:flex-start;flex-wrap:wrap}
.who{font-weight:650;font-size:17px}.mail{color:var(--muted);font-size:13px}
.tag{margin-left:auto;font-size:12px;font-weight:700;padding:4px 10px;border-radius:999px;white-space:nowrap}
.p3{color:var(--hi);background:var(--hi-bg)}.p2{color:var(--mid);background:var(--mid-bg)}.p1{color:var(--lo);background:var(--lo-bg)}
.subj{margin:6px 0 2px;font-weight:600}
.meta{color:var(--muted);font-size:13px}
.why{display:flex;flex-wrap:wrap;gap:6px;margin:10px 0}
.why span{font-size:12px;border:1px solid var(--line);border-radius:8px;padding:2px 8px;color:var(--muted)}
details{margin:6px 0 10px}summary{cursor:pointer;color:var(--muted);font-size:13px}
details pre{white-space:pre-wrap;font-family:inherit;font-size:13px;line-height:1.5;background:var(--bg);border-radius:10px;padding:10px 12px;margin:8px 0 0}
textarea{width:100%;min-height:150px;border:1px solid var(--line);border-radius:12px;padding:12px;font-family:inherit;font-size:14px;line-height:1.55;
background:var(--bg);color:var(--ink);resize:vertical}
.note{font-size:12px;color:var(--mid);margin:6px 0 0}
.src{font-size:12px;color:var(--muted);margin:6px 0 0}
.acts{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}
button,a.btn{font-family:inherit;font-weight:600;font-size:14px;line-height:1;border-radius:10px;padding:10px 14px;border:1px solid var(--line);background:var(--card);color:var(--ink);cursor:pointer;text-decoration:none}
a.btn.main{background:#6d28d9;border-color:#6d28d9;color:#fff}
button.ok{color:var(--ok)}
.empty{background:var(--card);border:1px dashed var(--line);border-radius:18px;padding:30px;text-align:center;color:var(--muted)}
footer{margin-top:30px;color:var(--muted);font-size:13px;line-height:1.6}
footer a{color:var(--accent)}
"""

JS = """
const KEY='follow-up-radar-done';
function load(){try{return JSON.parse(localStorage.getItem(KEY)||'{}')}catch(e){return {}}}
function save(d){try{localStorage.setItem(KEY,JSON.stringify(d))}catch(e){}}
const done=load();
document.querySelectorAll('.card').forEach(card=>{
  const id=card.dataset.id, ta=card.querySelector('textarea'), open=card.querySelector('a.main');
  const sync=()=>{open.href='mailto:'+card.dataset.to+'?subject='+encodeURIComponent(card.dataset.subject)+'&body='+encodeURIComponent(ta.value)};
  const fit=()=>{ta.style.height='auto';ta.style.height=(ta.scrollHeight+4)+'px'};
  ta.addEventListener('input',()=>{sync();fit()}); sync(); requestAnimationFrame(fit);
  if(done[id]) card.classList.add('done');
  card.querySelector('.copy').addEventListener('click',async e=>{
    try{await navigator.clipboard.writeText(ta.value)}catch(err){ta.select();document.execCommand('copy')}
    e.target.textContent='Copied';setTimeout(()=>e.target.textContent='Copy',1500)});
  card.querySelector('.ok').addEventListener('click',e=>{
    const d=load(); d[id]=!d[id]; save(d); card.classList.toggle('done',d[id]);
    e.target.textContent=d[id]?'Undo':'Mark as done'});
  if(done[id]) card.querySelector('.ok').textContent='Undo';
});
"""


def _ago(days: int) -> str:
    return "today" if days == 0 else ("1 day" if days == 1 else f"{days} days")


def render(loops: list, stats: dict, source: str, generated: datetime) -> str:
    cards = []
    for lp in loops:
        reply_subject = lp.subject if lp.subject.lower().startswith("re:") else f"Re: {lp.subject}"
        attempt = "first follow-up" if lp.followups_sent == 0 else "last follow-up (you already sent 1)"
        name = escape(lp.contact_name or lp.contact_email)
        note = f'<p class="note">{escape(lp.draft_note)}</p>' if lp.draft_note else ""
        src = "Draft from a template" if lp.draft_source == "template" else f"Draft by {escape(lp.draft_source)}, checked for made-up numbers"
        cards.append(f"""
<section class="card" data-id="{escape(lp.message_id or lp.contact_email + lp.subject)}" data-to="{escape(lp.contact_email)}" data-subject="{escape(reply_subject)}">
  <div class="top"><div><div class="who">{name}</div><div class="mail">{escape(lp.contact_email)}</div></div>
  <span class="tag p{lp.priority}">{escape(lp.category_label)}</span></div>
  <div class="subj">{escape(lp.subject)}</div>
  <div class="meta">Waiting {_ago(lp.days_waiting)} since your last email · {attempt}</div>
  <div class="why">{''.join(f'<span>{escape(r)}</span>' for r in lp.reasons)}</div>
  <details><summary>What you sent on {lp.first_sent.strftime('%b %d')}</summary><pre>{escape(lp.snippet)}</pre></details>
  <textarea aria-label="Follow-up draft">{escape(lp.draft)}</textarea>{note}
  <p class="src">{src}. Edit it before you send.</p>
  <div class="acts"><a class="btn main" href="#">Open in email</a><button class="copy">Copy</button><button class="ok">Mark as done</button></div>
</section>""")

    body = "".join(cards) if cards else '<div class="empty">Nothing went quiet. Every conversation in this window got an answer, or it\'s too soon to follow up.</div>'
    chips = [
        ("threads checked", stats.get("threads", 0)),
        ("got an answer", stats.get("answered", 0)),
        ("not asking for anything", stats.get("not_an_ask", 0)),
        ("too soon to chase", stats.get("too_recent", 0)),
        ("you already followed up twice", stats.get("gave_up", 0)),
    ]
    stat_html = "".join(f'<span class="stat"><b>{v}</b> {escape(k)}</span>' for k, v in chips)
    n = len(loops)
    title = f"<b>{n}</b> conversation{'s' if n != 1 else ''} went quiet" if n else "<b>All clear</b>"
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Follow-up Radar</title><style>{CSS}</style></head><body><main>
<div class="kick">Follow-up Radar · {generated.strftime('%b %d, %Y')}</div>
<h1>{title}</h1>
<p class="sub">These people haven't replied to something that needs an answer. Most important first.</p>
<div class="stats">{stat_html}</div>
{body}
<footer>Read from {escape(source)}. Read-only: nothing was sent, moved, or marked as read.
Nothing leaves your computer unless you chose a cloud model for drafts.<br>
Made with <a href="{REPO_URL}">follow-up-radar</a>.</footer>
</main><script>{JS}</script></body></html>"""


def write_outputs(loops: list, stats: dict, source: str, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    page = out_dir / "follow-ups.html"
    page.write_text(render(loops, stats, source, now), encoding="utf-8")
    rows = [{
        "name": lp.contact_name, "email": lp.contact_email, "subject": lp.subject, "type": lp.category_label,
        "days_waiting": lp.days_waiting, "followups_sent": lp.followups_sent,
        "last_sent": lp.last_sent.isoformat(), "why": "; ".join(lp.reasons), "draft": lp.draft,
    } for lp in loops]
    with (out_dir / "follow-ups.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()) if rows else ["name"])
        writer.writeheader()
        writer.writerows(rows)
    (out_dir / "follow-ups.json").write_text(json.dumps({"stats": stats, "follow_ups": rows}, indent=2), encoding="utf-8")
    return page
