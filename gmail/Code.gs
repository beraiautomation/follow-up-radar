/**
 * Follow-up Radar for Gmail
 * https://github.com/beraiautomation/follow-up-radar
 *
 * Every morning it finds the emails you sent that asked for something (a quote, an invoice,
 * a meeting, a question) and never got a reply. For each one it puts a short follow-up in your
 * Gmail Drafts, inside the same conversation, and lists them in a Google Sheet.
 *
 * It never emails your customers. You open Drafts, check the text, and press Send yourself.
 * The only email it sends is a short morning summary to you (turn it off below).
 *
 * Setup: paste this file into script.google.com, then run `setup` once. See gmail/SETUP.md.
 */

// ---------------------------------------------------------------- settings you can change
var CONFIG = {
  DAYS_BACK: 30,             // look at emails you sent in the last 30 days
  WAIT_DAYS: 3,              // only flag a conversation after 3 days with no reply
  MAX_FOLLOWUPS: 2,          // stop suggesting after you've followed up twice
  IGNORE_DOMAINS: [],        // e.g. ['mycompany.com'] to skip your own team
  SIGN_OFF: '',              // your name for "Thanks, ...". Empty = your first name from Gmail
  CREATE_DRAFTS: true,       // put follow-up drafts in Gmail Drafts
  SEND_SUMMARY_TO_ME: true,  // email yourself a short list each morning
  RUN_AT_HOUR: 7             // when the daily check runs (your time zone)
};

// ---------------------------------------------------------------- the rules (plain JavaScript)
var FREEMAIL = ['gmail.com', 'googlemail.com', 'outlook.com', 'hotmail.com', 'live.com', 'msn.com', 'yahoo.com',
  'icloud.com', 'me.com', 'mac.com', 'aol.com', 'proton.me', 'protonmail.com', 'gmx.com', 'mail.com', 'zoho.com',
  'yandex.com', 'fastmail.com', 'hey.com'];

var CATEGORIES = [
  { name: 'quote', label: 'Quote or proposal', priority: 3,
    re: /\b(quote|quotation|estimate|proposal|pricing|price list|bid|scope of work|sow)\b/ },
  { name: 'invoice', label: 'Invoice or payment', priority: 3,
    re: /\b(invoice|payment|balance due|overdue|amount due|outstanding balance|remittance)\b/ },
  { name: 'meeting', label: 'Meeting or call', priority: 2,
    re: /\b(meet|meeting|call|schedule|availability|available|calendar|book a time|zoom|teams link|demo)\b/ },
  { name: 'question', label: 'Waiting on an answer', priority: 1,
    re: /\b(let me know|get back to me|your thoughts|can you confirm|please confirm|could you confirm|approve|approval|sign off|sign the|any questions)\b/ }
];
var ATTACH_HINT = /(quote|proposal|estimate|invoice|contract|agreement|sow)/i;
var JUST_THANKS = /^\W*(thanks|thank you|thx|cheers|got it|sounds good|great|perfect|ok|okay|will do|noted)\b/i;
var NOREPLY = /(no-?reply|do-?not-?reply|mailer-daemon|notifications?@|bounce)/i;
var GENERIC_NAME = /\b(group|desk|team|inc|llc|ltd|gmbh|co|company|corp|accounts?|billing|support|sales|office|orders?|info|admin|reception|services?|department|dept|hr|payables?)\b/i;
var GENERIC_LOCAL = /^(accounts?|accounting|ap|ar|billing|orders?|info|sales|support|office|admin|hello|contact|team|hr|payables?|invoices?|bookings?|enquiries|inquiries)$/;
var QUOTE_START = /^(on .{3,120}wrote:|-{2,}\s*original message\s*-{2,}|from:\s.+|sent from my \w+|_{5,})\s*$/i;

function parseAddressList(value) {
  var out = [];
  String(value || '').split(/,(?=(?:[^"]*"[^"]*")*[^"]*$)/).forEach(function (part) {
    var m = part.match(/^\s*"?([^"<]*?)"?\s*<([^>]+)>\s*$/);
    if (m) out.push({ name: m[1].trim(), email: m[2].trim().toLowerCase() });
    else if (part.indexOf('@') >= 0) out.push({ name: '', email: part.trim().toLowerCase() });
  });
  return out;
}

function domainOf(email) {
  var i = email.lastIndexOf('@');
  return i >= 0 ? email.slice(i + 1).toLowerCase() : '';
}

function stripQuoted(text) {
  var out = [];
  var lines = String(text || '').replace(/\r\n/g, '\n').split('\n');
  for (var i = 0; i < lines.length; i++) {
    var line = lines[i];
    if (QUOTE_START.test(line.trim())) break;
    if (/^\s*>/.test(line)) continue;
    out.push(line.replace(/\s+$/, ''));
  }
  return out.join('\n').trim().replace(/\n{3,}/g, '\n\n');
}

/** Does this email ask for something? Returns null, or {name, label, priority, reasons, word}. */
function classify(subject, body, attachments) {
  var low = (subject + '\n' + body).toLowerCase();
  var hits = [], reasons = [];
  CATEGORIES.forEach(function (c) {
    var m = low.match(c.re);
    if (m) { hits.push(c); reasons.push('mentions "' + m[0] + '"'); }
  });
  var files = (attachments || []).filter(function (f) { return ATTACH_HINT.test(f || ''); });
  if (files.length) {
    reasons.push('attached ' + files.slice(0, 2).join(', '));
    if (!hits.length) hits.push(CATEGORIES[0]);
  }
  var asks = body.indexOf('?') >= 0;
  if (asks) reasons.push('asks a question');
  if (!hits.length && !asks) return null;
  var trimmed = body.trim();
  if (JUST_THANKS.test(trimmed) && trimmed.length < 120 && !files.length && !asks) return null;
  var best = hits.length ? hits.reduce(function (a, b) { return b.priority > a.priority ? b : a; }) : CATEGORIES[3];
  var words = (low + ' ' + files.join(' ').toLowerCase().replace(/[_.-]/g, ' '))
    .match(/\b(proposal|estimate|quote|quotation|scope of work|sow)\b/);
  var word = words ? ({ quotation: 'quote', 'scope of work': 'proposal', sow: 'proposal' }[words[1]] || words[1]) : 'quote';
  return { name: best.name, label: best.label, priority: best.priority, reasons: reasons, word: word };
}

/**
 * Decide one Gmail conversation. msgs: plain objects, oldest first:
 * {from, fromName, to: [{name,email}], date (Date), subject, body, attachments: [names], auto, isDraft}
 * Returns {status, ...}. status is 'follow_up' for a quiet conversation, otherwise a reason it isn't.
 */
function decideThread(msgs, me, now, cfg) {
  var mine = function (m) { return me.indexOf(m.from) >= 0; };
  var real = msgs.filter(function (m) { return !m.isDraft; });
  if (!real.length) return { status: 'empty' };
  var last = real[real.length - 1];
  if (!mine(last)) return { status: 'their_turn' };          // they wrote last: the next step is yours

  var lastIncoming = -1;
  for (var i = 0; i < real.length; i++) if (!mine(real[i]) && !real[i].auto) lastIncoming = i;
  var streak = real.slice(lastIncoming + 1).filter(mine);
  var ask = streak[0];
  var ignore = (cfg.IGNORE_DOMAINS || []).map(function (d) { return d.toLowerCase().replace(/^@/, ''); });
  var contacts = ask.to.filter(function (r) {
    return me.indexOf(r.email) < 0 && ignore.indexOf(domainOf(r.email)) < 0 && !/no-?reply|do-?not-?reply/.test(r.email);
  });
  if (!contacts.length) return { status: 'no_contact' };
  var verdict = classify(ask.subject, stripQuoted(ask.body), ask.attachments);
  if (!verdict) return { status: 'not_an_ask' };
  var days = Math.floor((now - last.date) / 86400000);
  if (days < cfg.WAIT_DAYS) return { status: 'too_recent' };
  var followups = streak.length - 1;
  if (followups >= cfg.MAX_FOLLOWUPS) return { status: 'gave_up' };
  return {
    status: 'follow_up', contactName: contacts[0].name, contactEmail: contacts[0].email,
    allTo: contacts.map(function (c) { return c.email; }), subject: ask.subject, category: verdict.name,
    label: verdict.label, priority: verdict.priority, reasons: verdict.reasons, word: verdict.word,
    firstSent: ask.date, lastSent: last.date, daysWaiting: days, followupsSent: followups
  };
}

function firstName(name, email) {
  name = String(name || '').trim();
  var local = String(email || '').split('@')[0].toLowerCase();
  if (!name || name.indexOf('@') >= 0 || GENERIC_NAME.test(name) || GENERIC_LOCAL.test(local)) return '';
  var first = name.split(/[\s,]+/)[0];
  return first.charAt(0).toUpperCase() + first.slice(1);
}

var MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

function topicOf(subject, category) {
  var s = String(subject || '').replace(/^\s*((re|fw|fwd)\s*:\s*)+/i, '').trim();
  if (category === 'quote' || category === 'invoice') {
    var stripped = s.replace(/^(quote|quotation|estimate|proposal|invoice)\b\s*(for\b|:|-)?\s*/i, '').trim();
    s = stripped || s;
  }
  return s || 'my last email';
}

function makeDraft(loop, signOff) {
  var date = MONTHS[loop.firstSent.getMonth()] + ' ' + loop.firstSent.getDate();
  var topic = topicOf(loop.subject, loop.category);
  var last = loop.followupsSent >= 1;
  var T = {
    quote: last
      ? "I haven't heard back about the " + loop.word + ' (' + topic + "), so I'll guess the timing isn't right for now. If anything changes, just reply here and I'll pick it up."
      : 'Just checking in on the ' + loop.word + ' I sent on ' + date + ' (' + topic + '). Do you have any questions, or would you like to go ahead?\n\nHappy to change anything if it helps.',
    invoice: last
      ? "I'm following up again on the invoice I sent on " + date + ' (' + topic + "). Could you confirm a payment date this week? If there's a problem with the invoice, tell me and I'll fix it."
      : 'A friendly reminder about the invoice I sent on ' + date + ' (' + topic + "). Could you let me know when payment is planned?\n\nIf you've already paid, thank you, and please ignore this.",
    meeting: last
      ? 'One more try on "' + topic + "\". If now isn't a good time, no problem. Reply whenever it suits you and we'll find a time."
      : 'Following up on my email about "' + topic + '". Would a quick call this week or next work for you?',
    question: last
      ? 'Checking one last time about "' + topic + '". If someone else should handle this, could you point me to them?'
      : 'Bringing this back to the top of your inbox: "' + topic + '". When you get a moment, could you let me know?'
  };
  var who = firstName(loop.contactName, loop.contactEmail);
  return (who ? 'Hi ' + who + ',' : 'Hi there,') + '\n\n' + T[loop.category] + '\n\nThanks,' + (signOff ? '\n' + signOff : '');
}

// ---------------------------------------------------------------- Gmail, Sheets and triggers

/** Run this once. It makes the sheet, schedules the daily check, and runs the first one. */
function setup() {
  var props = PropertiesService.getUserProperties();
  if (!props.getProperty('SHEET_ID')) {
    var ss = SpreadsheetApp.create('Follow-up Radar');
    props.setProperty('SHEET_ID', ss.getId());
  }
  stopRadar();
  ScriptApp.newTrigger('runRadar').timeBased().everyDays(1).atHour(CONFIG.RUN_AT_HOUR).create();
  var result = runRadar();
  Logger.log('Set up. Your sheet: ' + SpreadsheetApp.openById(props.getProperty('SHEET_ID')).getUrl());
  return result;
}

/** Stops the daily check. Your sheet and drafts stay. */
function stopRadar() {
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'runRadar') ScriptApp.deleteTrigger(t);
  });
}

function myAddresses() {
  var list = [Session.getActiveUser().getEmail()].concat(GmailApp.getAliases());
  return list.filter(Boolean).map(function (a) { return a.toLowerCase(); });
}

function toPlain(m) {
  var from = parseAddressList(m.getFrom())[0] || { name: '', email: '' };
  var auto = NOREPLY.test(from.email) || !!m.getHeader('List-Unsubscribe') || !!m.getHeader('List-Id') ||
    /^(bulk|list|junk)$/i.test(m.getHeader('Precedence') || '') ||
    ((m.getHeader('Auto-Submitted') || 'no').toLowerCase() !== 'no');
  return {
    from: from.email, fromName: from.name, to: parseAddressList(m.getTo()), date: m.getDate(),
    subject: m.getSubject(), body: m.getPlainBody().slice(0, 4000),
    attachments: m.getAttachments().map(function (a) { return a.getName(); }),
    auto: auto, isDraft: m.isDraft(), raw: m
  };
}

/** They may have answered in a separate email (new subject) or a colleague answered. */
function answeredElsewhere(loop) {
  var after = Utilities.formatDate(loop.lastSent, Session.getScriptTimeZone(), 'yyyy/MM/dd');
  var d = domainOf(loop.contactEmail);
  var who = FREEMAIL.indexOf(d) >= 0 ? 'from:' + loop.contactEmail : 'from:@' + d;
  var free = FREEMAIL.indexOf(d) >= 0;
  return GmailApp.search(who + ' after:' + after, 0, 5).some(function (t) {
    return t.getMessages().some(function (m) {
      var sender = (parseAddressList(m.getFrom())[0] || { email: '' }).email;
      var related = free ? sender === loop.contactEmail : domainOf(sender) === d;
      return related && !m.isDraft() && m.getDate() > loop.lastSent;
    });
  });
}

function threadHasDraft(threadId) {
  return GmailApp.getDrafts().some(function (d) {
    try { return d.getMessage().getThread().getId() === threadId; } catch (e) { return false; }
  });
}

function encodeHeader(text) {
  return /^[\x20-\x7e]*$/.test(text) ? text : '=?UTF-8?B?' + Utilities.base64Encode(text, Utilities.Charset.UTF_8) + '?=';
}

/** A draft reply inside the same conversation. Needs the Gmail API service (see SETUP.md); falls back to a new draft. */
function createDraft(thread, lastMsg, loop, body) {
  var subject = /^re:/i.test(loop.subject) ? loop.subject : 'Re: ' + loop.subject;
  if (typeof Gmail !== 'undefined') {
    var msgId = lastMsg.getHeader('Message-ID');
    var refs = ((lastMsg.getHeader('References') || '') + ' ' + msgId).trim();
    var raw = ['To: ' + loop.allTo.join(', '), 'Subject: ' + encodeHeader(subject), 'In-Reply-To: ' + msgId,
      'References: ' + refs, 'MIME-Version: 1.0', 'Content-Type: text/plain; charset=UTF-8', '', body].join('\r\n');
    Gmail.Users.Drafts.create({ message: { raw: Utilities.base64EncodeWebSafe(raw, Utilities.Charset.UTF_8),
      threadId: thread.getId() } }, 'me');
    return 'in thread';
  }
  GmailApp.createDraft(loop.allTo.join(','), subject, body);
  return 'new draft';
}

/** The daily check. Safe to run by hand any time. */
function runRadar() {
  var me = myAddresses();
  var now = new Date();
  var signOff = CONFIG.SIGN_OFF;
  var loops = [], stats = { checked: 0, answered: 0, not_an_ask: 0, too_recent: 0, gave_up: 0, drafts: 0 };

  var start = 0, threads = [];
  do {
    var page = GmailApp.search('in:sent newer_than:' + CONFIG.DAYS_BACK + 'd', start, 100);
    threads = threads.concat(page);
    start += 100;
  } while (page.length === 100 && start < 500);

  threads.forEach(function (thread) {
    var msgs = thread.getMessages().map(toPlain);
    stats.checked++;
    var r = decideThread(msgs, me, now, CONFIG);
    if (r.status !== 'follow_up') {
      if (stats[r.status] !== undefined) stats[r.status]++;
      if (r.status === 'their_turn') stats.answered++;
      return;
    }
    if (answeredElsewhere(r)) { stats.answered++; return; }
    if (!signOff) {
      var mineMsg = msgs.filter(function (m) { return me.indexOf(m.from) >= 0 && m.fromName; })[0];
      signOff = mineMsg ? mineMsg.fromName.split(' ')[0] : '';
    }
    r.draft = makeDraft(r, signOff);
    r.threadId = thread.getId();
    r.link = 'https://mail.google.com/mail/u/0/#all/' + thread.getId();
    r.draftStatus = 'not created';
    if (CONFIG.CREATE_DRAFTS) {
      if (threadHasDraft(thread.getId())) {
        r.draftStatus = 'already in Drafts';
      } else {
        var lastReal = msgs.filter(function (m) { return !m.isDraft; }).pop().raw;
        r.draftStatus = 'created (' + createDraft(thread, lastReal, r, r.draft) + ')';
        stats.drafts++;
      }
    }
    loops.push(r);
  });

  loops.sort(function (a, b) { return (b.priority - a.priority) || (b.daysWaiting - a.daysWaiting); });
  writeSheet(loops, stats, now);
  if (CONFIG.SEND_SUMMARY_TO_ME && loops.length) sendSummary(me[0], loops);
  return { found: loops.length, stats: stats };
}

function writeSheet(loops, stats, now) {
  var id = PropertiesService.getUserProperties().getProperty('SHEET_ID');
  if (!id) return;
  var sheet = SpreadsheetApp.openById(id).getSheets()[0];
  sheet.clear();
  sheet.getRange(1, 1).setValue('Follow-up Radar · ' + now.toDateString() + ' · ' + loops.length +
    ' conversation(s) went quiet · ' + stats.checked + ' checked, ' + stats.answered + ' answered');
  var header = ['Who', 'Email', 'Subject', 'Type', 'Days waiting', 'Follow-ups sent', 'Draft', 'Open in Gmail', 'Follow-up text'];
  var rows = loops.map(function (l) {
    return [l.contactName || l.contactEmail, l.contactEmail, l.subject, l.label, l.daysWaiting, l.followupsSent,
      l.draftStatus, l.link, l.draft];
  });
  sheet.getRange(3, 1, 1, header.length).setValues([header]).setFontWeight('bold');
  if (rows.length) sheet.getRange(4, 1, rows.length, header.length).setValues(rows).setVerticalAlignment('top');
  sheet.setFrozenRows(3);
  sheet.setColumnWidth(9, 420);
  if (rows.length) sheet.getRange(4, 9, rows.length, 1).setWrap(true);
}

function sendSummary(to, loops) {
  var lines = loops.map(function (l) {
    return '- ' + (l.contactName || l.contactEmail) + ': ' + l.subject + ' (' + l.label + ', ' + l.daysWaiting + ' days)';
  });
  GmailApp.sendEmail(to, 'Follow-up Radar: ' + loops.length + ' conversation(s) went quiet',
    'These people haven\'t replied yet. Your drafts are waiting in Gmail Drafts. Check each one, then send.\n\n' +
    lines.join('\n') + '\n\nFollow-up Radar never emails your customers. You send each follow-up yourself.');
}

// Lets the tests load the rules in Node. Apps Script ignores this.
if (typeof module !== 'undefined') {
  module.exports = { classify: classify, decideThread: decideThread, makeDraft: makeDraft, firstName: firstName,
    stripQuoted: stripQuoted, parseAddressList: parseAddressList, topicOf: topicOf };
}
