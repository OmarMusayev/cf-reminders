#!/usr/bin/env python3
"""Fetches Codeforces + interview data and writes JSON dumps under data/.

Run from GitHub Actions every 2h. The Anthropic routine reads these files
out of the cloned repo.

Outputs:
  data/contests.json           — upcoming contests
  data/user.json               — current rating, rank, handle
  data/rating_history.json     — past contests with rating changes
  data/submissions_recent.json — last 30 days of submissions
  data/solved.json             — set of all solved problem keys
  data/problemset.json         — slim list of rated problems
  data/adaptation.json         — derived: rating boost from stretch hit-rate, per-tag solve rates
  data/leetcode_daily.json     — LeetCode's daily challenge (fresh each day)
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


LEETCODE_DAILY_QUERY = """
query questionOfToday {
  activeDailyCodingChallengeQuestion {
    date
    link
    question {
      questionFrontendId
      title
      titleSlug
      difficulty
      topicTags { name }
    }
  }
}
"""


def fetch_leetcode_daily():
    """LeetCode's public daily challenge via their GraphQL. No auth."""
    r = requests.post(
        "https://leetcode.com/graphql/",
        json={"query": LEETCODE_DAILY_QUERY, "operationName": "questionOfToday"},
        headers={"Referer": "https://leetcode.com/"},
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    d = r.json()["data"]["activeDailyCodingChallengeQuestion"]
    q = d["question"]
    write_json(DATA_DIR / "leetcode_daily.json", {
        "date": d["date"],
        "url": "https://leetcode.com" + d["link"],
        "id": q["questionFrontendId"],
        "title": q["title"],
        "slug": q["titleSlug"],
        "difficulty": q["difficulty"],
        "tags": [t["name"] for t in q["topicTags"]],
    })


def compute_adaptation():
    """Derive a rating boost (from stretch hit-rate) and per-tag solve rates from recent submissions.

    The routine reads adaptation.json to:
      - use `effective_rating` (= CF rating + boost) when picking band centers
      - bias TOPIC_A/TOPIC_B picks toward tags with the lowest solve rates (user's weak spots)
    """
    user = json.loads((DATA_DIR / "user.json").read_text())
    subs = json.loads((DATA_DIR / "submissions_recent.json").read_text())["submissions"]
    rating = user.get("rating") or 1200

    # ----- Difficulty self-tuning: stretch hit-rate over last 14 days -----
    stretch_floor = rating + 100
    cutoff_14d = (NOW - timedelta(days=14)).timestamp()
    stretch_attempts = {}  # key -> solved?
    for s in subs:
        p = s.get("problem", {})
        if not p.get("rating") or p["rating"] < stretch_floor:
            continue
        if (s.get("creationTimeSeconds") or 0) < cutoff_14d:
            continue
        key = f"{p.get('contestId')}-{p.get('index')}"
        if key not in stretch_attempts:
            stretch_attempts[key] = False
        if s.get("verdict") == "OK":
            stretch_attempts[key] = True
    n_attempts = len(stretch_attempts)
    n_solved = sum(stretch_attempts.values())
    if n_attempts >= 5:
        rate = n_solved / n_attempts
        if rate > 0.5:
            boost = 50
        elif rate < 0.2:
            boost = -50
        else:
            boost = 0
    else:
        boost = 0  # insufficient data

    # ----- Per-tag solve rate over last 30 days -----
    cutoff_30d = (NOW - timedelta(days=30)).timestamp()
    tag_problems = {}  # tag -> { "attempted": set, "solved": set }
    for s in subs:
        if (s.get("creationTimeSeconds") or 0) < cutoff_30d:
            continue
        p = s.get("problem", {})
        tags = p.get("tags") or []
        if not tags or p.get("contestId") is None:
            continue
        key = f"{p['contestId']}-{p.get('index')}"
        ok = s.get("verdict") == "OK"
        for tag in tags:
            d = tag_problems.setdefault(tag, {"attempted": set(), "solved": set()})
            d["attempted"].add(key)
            if ok:
                d["solved"].add(key)
    tag_stats = {
        tag: {
            "attempted": len(v["attempted"]),
            "solved": len(v["solved"]),
            "rate": (len(v["solved"]) / len(v["attempted"])) if v["attempted"] else None,
        }
        for tag, v in tag_problems.items()
    }

    write_json(DATA_DIR / "adaptation.json", {
        "base_rating": rating,
        "rating_boost": boost,
        "effective_rating": rating + boost,
        "stretch_stats": {
            "window_days": 14,
            "attempts": n_attempts,
            "solved": n_solved,
            "rate": (n_solved / n_attempts) if n_attempts else None,
        },
        "tag_stats": tag_stats,
    })


def main():
    fetch_contests()
    fetch_user()
    fetch_rating_history()
    fetch_submissions_and_solved()
    fetch_problemset()
    # User-derived: needs user.json + submissions_recent.json
    compute_adaptation()
    # External: don't let a LeetCode hiccup fail the whole run
    try:
        fetch_leetcode_daily()
    except Exception as e:
        print(f"leetcode_daily fetch failed (non-fatal): {e}")
    print(f"Wrote data files at {NOW.isoformat()}")


if __name__ == "__main__":
    main()
