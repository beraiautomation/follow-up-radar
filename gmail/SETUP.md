# Follow-up Radar for Gmail: setup

No installing, no terminal. It runs inside your own Google account. About 5 minutes.

**What it does every morning**
- Finds the emails you sent that asked for something (a quote, an invoice, a meeting, a question) and got no reply.
- Puts a short, polite follow-up for each one in your **Gmail Drafts**, inside the same conversation.
- Lists them in a Google Sheet called **Follow-up Radar**, and emails you a short summary.

**What it never does:** email your customers. You open Drafts, read each one, change anything you
want, and press Send yourself.

## 1. Create the script

1. Go to [script.google.com](https://script.google.com) and click **New project**.
2. Delete the few lines that are already there.
3. Open [Code.gs](https://raw.githubusercontent.com/beraiautomation/follow-up-radar/main/gmail/Code.gs),
   select everything (Ctrl+A or Cmd+A), copy it, and paste it into the empty editor.
4. Click **Untitled project** at the top and name it **Follow-up Radar**.
5. Click the **Save** icon.

## 2. Turn on the Gmail service (recommended)

This lets the drafts land **inside the original conversation**, so your customer sees a normal reply.

1. On the left, next to **Services**, click **+**.
2. Pick **Gmail API** and click **Add**.

If you skip this, the drafts still work, but each one starts a new email with "Re:" in the subject.

## 3. Run it once

1. At the top, in the box next to **Debug**, choose **setup**.
2. Click **Run**.
3. Google asks for permission. Click **Review permissions** and pick your account.
4. You'll see **"Google hasn't verified this app."** That's normal: it's your own script, and
   only you can run it. Click **Advanced**, then **Go to Follow-up Radar (unsafe)**, then **Allow**.

It asks to read your email (to find the quiet conversations), manage drafts (to save the follow-ups),
send email (only the morning summary to you), and create a spreadsheet.

When it finishes, check your **Gmail Drafts** and the **Follow-up Radar** sheet in Google Drive.
From now on it runs every morning at 7.

## Change the settings

At the top of the code, change any value in `CONFIG` and click **Save**:

| Setting | What it does | Default |
|---|---|---|
| `DAYS_BACK` | How far back to look | 30 days |
| `WAIT_DAYS` | Days without a reply before it suggests a follow-up | 3 |
| `MAX_FOLLOWUPS` | Stop after this many follow-ups, so you don't nag | 2 |
| `IGNORE_DOMAINS` | Skip your own team, e.g. `['mycompany.com']` | none |
| `SIGN_OFF` | Your name for "Thanks, ..." | your first name |
| `CREATE_DRAFTS` | Save drafts in Gmail | on |
| `SEND_SUMMARY_TO_ME` | Morning summary email to you | on |
| `RUN_AT_HOUR` | Hour of the daily check | 7 |

## Pause or remove it

- **Pause:** choose **stopRadar** in the box at the top and click **Run**.
- **Remove completely:** delete the project at script.google.com, then remove its access at
  [myaccount.google.com/permissions](https://myaccount.google.com/permissions).

Your drafts and the sheet stay until you delete them.

## Good to know

- It checks up to 500 conversations per run, which is plenty for most small businesses.
- If someone answered by phone or text, the tool can't know. Just delete that draft.
- It won't make a second draft for a conversation that already has one in Drafts.
