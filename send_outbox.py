#!/usr/bin/env python3
"""Sends Gmail drafts whose subject starts with the outbox prefix '[CF]'.

The Anthropic routine composes emails as drafts (via the claude.ai Gmail
MCP connector). Those drafts sit in the user's Drafts folder with subjects
like `[CF] Daily Digest 2026-05-12`. This script runs on the next GitHub
Actions tick, finds those drafts, and actually sends them.

Idempotency: once a draft is sent, it's gone from Drafts. So re-running
this script won't duplicate-send.
"""
import os
import sys

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

OUTBOX_PREFIX = "[CF]"
SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/gmail.modify",
]


def gmail_service():
    creds = Credentials(
        None,
        refresh_token=os.environ["GOOGLE_REFRESH_TOKEN"],
        client_id=os.environ["GOOGLE_CLIENT_ID"],
        client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
        token_uri="https://oauth2.googleapis.com/token",
        scopes=SCOPES,
    )
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def list_outbox_drafts(service):
    """Return list of (draft_id, subject) for drafts whose subject starts with the outbox prefix."""
    out = []
    page_token = None
    while True:
        resp = service.users().drafts().list(
            userId="me",
            maxResults=100,
            pageToken=page_token,
        ).execute()
        for d in resp.get("drafts", []):
            full = service.users().drafts().get(
                userId="me", id=d["id"], format="metadata"
            ).execute()
            headers = full.get("message", {}).get("payload", {}).get("headers", [])
            subject = next((h["value"] for h in headers if h["name"].lower() == "subject"), "")
            if subject.startswith(OUTBOX_PREFIX):
                out.append((d["id"], subject))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return out


def main():
    service = gmail_service()
    drafts = list_outbox_drafts(service)
    if not drafts:
        print("Outbox: no [CF]-prefixed drafts to send.")
        return

    sent = 0
    errors = []
    for draft_id, subject in drafts:
        try:
            service.users().drafts().send(userId="me", body={"id": draft_id}).execute()
            print(f"Sent: {subject}")
            sent += 1
        except HttpError as e:
            errors.append(f"{subject}: HTTP {e.resp.status} {e.reason}")
        except Exception as e:
            errors.append(f"{subject}: {e}")

    print(f"Outbox: sent {sent} / {len(drafts)}")
    if errors:
        print("Errors: " + "; ".join(errors))
        sys.exit(1)


if __name__ == "__main__":
    main()
