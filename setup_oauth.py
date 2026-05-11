#!/usr/bin/env python3
"""One-time helper: do the Google OAuth flow locally, print the refresh token.

Usage:
    python setup_oauth.py path/to/client_secret.json

Opens a browser, asks you to authorize Calendar access, then prints the three
values you need to paste into your GitHub repository secrets.
"""
import sys

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/gmail.modify",
]


def main():
    if len(sys.argv) != 2:
        print("Usage: python setup_oauth.py <path-to-client_secret.json>", file=sys.stderr)
        sys.exit(1)

    flow = InstalledAppFlow.from_client_secrets_file(sys.argv[1], SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")

    print()
    print("=" * 64)
    print("OAuth complete. Add these three to your GitHub repository secrets:")
    print("(Repo → Settings → Secrets and variables → Actions → New secret)")
    print("=" * 64)
    print(f"GOOGLE_CLIENT_ID     = {creds.client_id}")
    print(f"GOOGLE_CLIENT_SECRET = {creds.client_secret}")
    print(f"GOOGLE_REFRESH_TOKEN = {creds.refresh_token}")
    print()


if __name__ == "__main__":
    main()
