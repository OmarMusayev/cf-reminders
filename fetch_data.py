#!/usr/bin/env python3
"""Fetches Codeforces data and writes JSON dumps under data/.

Run from GitHub Actions every 6h. The Anthropic routine reads these files
out of the cloned repo to avoid hitting codeforces.com directly (which the
routine environment can't reach).

Outputs:
  data/contests.json           — upcoming contests
  data/user.json               — current rating, rank, handle
  data/rating_history.json     — past contests with rating changes
  data/submissions_recent.json — last 30 days of submissions
  data/solved.json             — set of all solved problem keys
  data/problemset.json         — slim list of rated problems
"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

HANDLE = "Omar_Musayev"
DATA_DIR = Path(__file__).parent / "data"
TIMEOUT = 60
NOW = datetime.now(timezone.utc)


def cf_get(url):
    r = requests.get(url, timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json()
    if data.get("status") != "OK":
        raise RuntimeError(f"{url}: {data.get('status')}: {data.get('comment')}")
    return data["result"]


def write_json(path: Path, payload: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    out = {"fetched_at": NOW.isoformat(), **payload}
    path.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")


def fetch_contests():
    contests = cf_get("https://codeforces.com/api/contest.list?gym=false")
    upcoming = [c for c in contests if c.get("phase") == "BEFORE"]
    write_json(DATA_DIR / "contests.json", {"upcoming": upcoming})


def fetch_user():
    info = cf_get(f"https://codeforces.com/api/user.info?handles={HANDLE}")[0]
    write_json(DATA_DIR / "user.json", {
        "handle": HANDLE,
        "rating": info.get("rating"),
        "maxRating": info.get("maxRating"),
        "rank": info.get("rank"),
        "maxRank": info.get("maxRank"),
    })


def fetch_rating_history():
    hist = cf_get(f"https://codeforces.com/api/user.rating?handle={HANDLE}")
    write_json(DATA_DIR / "rating_history.json", {"history": hist})


def fetch_submissions_and_solved():
    subs = cf_get(f"https://codeforces.com/api/user.status?handle={HANDLE}&from=1&count=10000")
    cutoff = (NOW - timedelta(days=30)).timestamp()
    recent = []
    solved = set()
    for s in subs:
        p = s.get("problem", {})
        if s.get("verdict") == "OK" and "contestId" in p:
            solved.add(f"{p['contestId']}-{p['index']}")
        if s.get("creationTimeSeconds", 0) >= cutoff:
            recent.append({
                "id": s.get("id"),
                "contestId": s.get("contestId"),
                "creationTimeSeconds": s.get("creationTimeSeconds"),
                "verdict": s.get("verdict"),
                "problem": {
                    "contestId": p.get("contestId"),
                    "index": p.get("index"),
                    "name": p.get("name"),
                    "rating": p.get("rating"),
                    "tags": p.get("tags", []),
                },
                "participantType": s.get("author", {}).get("participantType"),
            })
    write_json(DATA_DIR / "solved.json", {"keys": sorted(solved)})
    write_json(DATA_DIR / "submissions_recent.json", {"submissions": recent})


def fetch_problemset():
    data = cf_get("https://codeforces.com/api/problemset.problems")
    problems = [
        {
            "contestId": p.get("contestId"),
            "index": p.get("index"),
            "name": p.get("name"),
            "rating": p.get("rating"),
            "tags": p.get("tags", []),
        }
        for p in data["problems"]
        if p.get("rating") is not None
    ]
    write_json(DATA_DIR / "problemset.json", {"problems": problems})


def main():
    fetch_contests()
    fetch_user()
    fetch_rating_history()
    fetch_submissions_and_solved()
    fetch_problemset()
    print(f"Wrote data files at {NOW.isoformat()}")


if __name__ == "__main__":
    main()
