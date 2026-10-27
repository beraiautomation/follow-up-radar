// Tests for the rules inside gmail/Code.gs. Run: node --test tests/
// The Gmail and Sheets parts need a Google account; the rules are plain JavaScript and run here.
const test = require('node:test');
const assert = require('node:assert');
const path = require('node:path');
const fs = require('node:fs');
const vm = require('node:vm');

const code = fs.readFileSync(path.join(__dirname, '..', 'gmail', 'Code.gs'), 'utf8');
const sandbox = { module: { exports: {} } };
vm.runInNewContext(code, sandbox);
const R = sandbox.module.exports;

const NOW = new Date('2026-11-01T12:00:00Z');
const ME = ['sam@riverarepairs.example'];
const CFG = { WAIT_DAYS: 3, MAX_FOLLOWUPS: 2, IGNORE_DOMAINS: [] };
const ago = (d) => new Date(NOW - d * 86400000);
const mine = (to, subject, body, d, extra = {}) => ({ from: ME[0], fromName: 'Sam Rivera', to: R.parseAddressList(to),
  date: ago(d), subject, body, attachments: [], auto: false, isDraft: false, ...extra });
const theirs = (from, subject, body, d, extra = {}) => ({ from, fromName: '', to: R.parseAddressList(ME[0]),
  date: ago(d), subject, body, attachments: [], auto: false, isDraft: false, ...extra });

test('a quote with no reply is a follow-up', () => {
  const r = R.decideThread([mine('Maria Lopez <maria@gmail.com>', 'Quote: bathroom tile', 'The quote is $1,450. Let me know.', 6)], ME, NOW, CFG);
  assert.equal(r.status, 'follow_up');
  assert.equal(r.category, 'quote');
  assert.equal(r.daysWaiting, 6);
  assert.match(R.makeDraft(r, 'Sam'), /^Hi Maria,\n\nJust checking in on the quote I sent on Oct 26 \(bathroom tile\)/);
});

test('they replied last: your turn, not a follow-up', () => {
  const r = R.decideThread([mine('p@gmail.com', 'Estimate', 'Estimate is $720. Any questions?', 9),
    theirs('p@gmail.com', 'Re: Estimate', 'Can you do Tuesday?', 8)], ME, NOW, CFG);
  assert.equal(r.status, 'their_turn');
});

test('old reply, then a new ask from you, is open', () => {
  const r = R.decideThread([mine('a@x.example', 'Deck', 'Can you send the measurements?', 10),
    theirs('a@x.example', 'Re: Deck', 'Here they are.', 9),
    mine('a@x.example', 'Re: Deck', 'Thanks! The quote is $2,000. Shall I book it?', 6)], ME, NOW, CFG);
  assert.equal(r.status, 'follow_up');
  assert.equal(r.followupsSent, 0);
});

test('second follow-up is the last one, third is never suggested', () => {
  const two = [mine('a@gmail.com', 'Proposal', 'Proposal attached. Your thoughts?', 20), mine('a@gmail.com', 'Re: Proposal', 'Any questions?', 10)];
  const r = R.decideThread(two, ME, NOW, CFG);
  assert.equal(r.followupsSent, 1);
  assert.match(R.makeDraft(r, 'Sam'), /I haven't heard back about the proposal/);
  const three = two.concat([mine('a@gmail.com', 'Re: Proposal', 'One last check?', 5)]);
  assert.equal(R.decideThread(three, ME, NOW, CFG).status, 'gave_up');
});

test('thanks notes, auto mail, too recent, ignored domains, drafts', () => {
  assert.equal(R.decideThread([mine('t@gmail.com', 'Thanks!', 'Thanks Tom, great working with you.', 6)], ME, NOW, CFG).status, 'not_an_ask');
  assert.equal(R.decideThread([mine('l@gmail.com', 'Quote', 'Quote is $380. Let me know!', 1)], ME, NOW, CFG).status, 'too_recent');
  assert.equal(R.decideThread([mine('boss@shop.example', 'Invoice', 'Can you approve the invoice?', 6)], ME, NOW,
    { ...CFG, IGNORE_DOMAINS: ['shop.example'] }).status, 'no_contact');
  assert.equal(R.decideThread([mine('x@gmail.com', 'Quote', 'Quote?', 6),
    theirs('news@shop.example', 'deals', 'sale', 5, { auto: true })], ME, NOW, CFG).status, 'their_turn');
  const withDraft = [mine('a@gmail.com', 'Quote', 'Quote is $5. Let me know.', 6), mine('a@gmail.com', 'Re: Quote', 'draft', 0, { isDraft: true })];
  assert.equal(R.decideThread(withDraft, ME, NOW, CFG).status, 'follow_up');
});

test('greetings for people and shared inboxes', () => {
  assert.equal(R.firstName('maria lopez', 'maria@gmail.com'), 'Maria');
  assert.equal(R.firstName('Delta Property Group', 'accounts@delta.example'), '');
  assert.equal(R.firstName('Jane', 'billing@x.example'), '');
  assert.equal(R.firstName('', 'x@gmail.com'), '');
});

test('proposal word comes from the attachment name', () => {
  const r = R.decideThread([mine('g@yahoo.com', 'Garage conversion', 'Attached is what we talked about.', 10,
    { attachments: ['Proposal_Garage_Conversion.pdf'] })], ME, NOW, CFG);
  assert.equal(r.word, 'proposal');
  assert.match(R.makeDraft(r, ''), /the proposal I sent on Oct 22 \(Garage conversion\)[\s\S]*Thanks,$/);
});

test('address lists with names and commas', () => {
  const list = R.parseAddressList('"Lopez, Maria" <Maria@Gmail.com>, bob@x.example');
  assert.deepEqual(JSON.parse(JSON.stringify(list)), [{ name: 'Lopez, Maria', email: 'maria@gmail.com' }, { name: '', email: 'bob@x.example' }]);
});

test('quoted history is ignored when deciding', () => {
  assert.equal(R.stripQuoted('Sounds good.\n\nOn Mon, Oct 5, 2026 at 9:00 Bob wrote:\n> Can you send the invoice?'), 'Sounds good.');
});

test('same rules as the Python version on the shared demo cases', () => {
  const invoice = R.decideThread([mine('Delta Property Group <accounts@deltaprop.example>', 'Invoice #1042 - unit 4B water heater',
    'Please find invoice #1042 for $860 attached.', 16, { attachments: ['Invoice_1042.pdf'] }),
  mine('Delta Property Group <accounts@deltaprop.example>', 'Re: Invoice #1042 - unit 4B water heater', 'Could you let me know when payment is planned?', 7)], ME, NOW, CFG);
  assert.equal(invoice.category, 'invoice');
  assert.equal(invoice.followupsSent, 1);
  assert.match(R.makeDraft(invoice, 'Sam'), /^Hi there,\n\nI'm following up again on the invoice I sent on Oct 16 \(#1042 - unit 4B water heater\)/);
});
