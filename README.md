# cf-reminders

Personal automation that keeps a Google Calendar and Gmail inbox in sync with Codeforces — contest reminders, registration windows, a daily problem-of-the-day, morning digests, and post-contest debriefs.

## How it works

Two systems talk through this repo:

**GitHub Actions** (this repo) runs every 6 hours. It:
- Fetches the contest list, user info, rating history, recent submissions, and full problemset from the Codeforces API
- Writes JSON dumps to `data/` and commits them back
- Sends any Gmail drafts whose subject starts with `[CF]` (via the Gmail API)

**A scheduled remote agent** (Anthropic Claude Code routine) runs once a day. It clones this repo, reads `data/*.json`, and:
- Creates Google Calendar events for upcoming contests (with 24h+1h popup+email reminders)
- Creates registration-window reminders for Div. 3 / Div. 4 / Educational rounds
- Picks a problem-of-the-day from your rating band that you haven't solved, schedules it on the calendar
- Composes a morning digest as a Gmail draft — current rating, today's POTD, upcoming contests in the next 7 days, streak status, recent rating change
- Composes post-contest debriefs as drafts — rating delta, problems solved/missed, links — for any rated contest within the last 48h
- Skips anything it has already done (idempotent via calendar tags and Gmail searches)

The agent can't send mail directly — its Gmail connector only exposes `create_draft` — so it queues drafts and the next GitHub Actions tick (within 6 hours) sends them.

```
┌────────────────────┐    every 6h     ┌─────────────────────┐
│  GitHub Actions    │ ───────────────►│  data/*.json        │
│  fetch_data.py     │   commits back   │  in this repo       │
└────────────────────┘                  └─────────┬───────────┘
                                                  │ clones
                                                  ▼
┌────────────────────┐                  ┌─────────────────────┐
│  Anthropic         │ ◄────────────────│  Daily routine      │
│  Calendar MCP      │  creates events  │  reads data,        │
│  Gmail MCP         │  creates drafts  │  composes content   │
└────────────────────┘                  └─────────┬───────────┘
                                                  │ drafts sit in Gmail
                                                  ▼
┌────────────────────┐    every 6h     ┌─────────────────────┐
│  GitHub Actions    │ ◄────────────────│  [CF]-prefixed       │
│  send_outbox.py    │   sends them    │  Gmail drafts       │
└────────────────────┘                  └─────────────────────┘
```

## File layout

| Path | Role |
| --- | --- |
| `.github/workflows/reminders.yml` | Cron + manual workflow (fetch + send) |
| `fetch_data.py` | Codeforces API → `data/*.json` |
| `send_outbox.py` | Sends Gmail drafts whose subject starts with `[CF]` |
| `setup_oauth.py` | One-time helper: runs the Google OAuth flow and prints a refresh token |
| `data/` | JSON dumps (refreshed every 6h, committed by the workflow) |

## Setup (to fork this for yourself)

### 1. Google Cloud credentials

- In Google Cloud Console, create a project and enable both the **Google Calendar API** and the **Gmail API**
- Configure the **OAuth consent screen**: External user type, app name of your choice, scopes `.../auth/calendar` and `.../auth/gmail.modify`, add yourself as a Test user, then **click "Publish app"** so the status is "In production" — an app left in "Testing" makes Google expire the refresh token after 7 days, which silently breaks `send_outbox.py`
- Create an **OAuth client ID** of type **Desktop app** and download the JSON as `client_secret.json`

### 2. Mint a refresh token locally

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python setup_oauth.py client_secret.json
```

Authorize in the browser that pops open. The script prints three values.

### 3. Add the three values as repository secrets

Repository → Settings → Secrets and variables → Actions → New repository secret:

- `GOOGLE_CLIENT_ID`
- `GOOGLE_CLIENT_SECRET`
- `GOOGLE_REFRESH_TOKEN`

### 4. Replace the Codeforces handle

In `fetch_data.py`, change `HANDLE = "Omar_Musayev"` to your own.

### 5. Trigger the workflow once

Push your changes, then go to the Actions tab and run the workflow manually to verify it can fetch data and send mail.

### 6. (Optional) Set up the daily agent

The agent is what creates calendar events and queues digest/debrief emails. Set up a Claude Code scheduled routine that clones this repo and follows a prompt similar to the one used here (see commit history if you want a starting point).

## Local development

```bash
source .venv/bin/activate
GOOGLE_CLIENT_ID=... GOOGLE_CLIENT_SECRET=... GOOGLE_REFRESH_TOKEN=... python fetch_data.py
GOOGLE_CLIENT_ID=... GOOGLE_CLIENT_SECRET=... GOOGLE_REFRESH_TOKEN=... python send_outbox.py
```

## Notes

- All Calendar event times are stored in UTC. Google Calendar renders them in the viewer's current device timezone, so events stay correct when you travel.
- The Codeforces API is rate-limited (~1 req/sec); the fetcher makes five calls per run, well within limits.
- Idempotency: contest events are tagged `[CF-<id>]`, registration windows `[CF-REG-<id>]`, problem-of-the-day `[CF-POTD-<date>]` in event descriptions. Digest and debrief emails are deduplicated by Gmail subject search.
