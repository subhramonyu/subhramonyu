#!/usr/bin/env python3
"""
Build merged-stats.svg from multiple GitHub usernames (public API).
GraphQL: commits, PRs, contribution calendar (365d). REST: stars on owned non-fork repos.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

# Rotates by UTC day + merged stats so the card refreshes copy when numbers (or the date) change.
_HUMOR_SUBTITLES = (
    "Rolling 365 days · the graph is honest; I supply the commits and the coping",
    "Public metrics only · private panic and prod hotfixes not included",
    "Green squares won’t pay rent · still oddly validating",
    "If these look good, tell my keyboard; it did most of the work",
    "Stats auto-refresh · my sleep schedule still on legacy cron",
    "Fewer meetings, more meaningful diffs · that’s the dream",
    "Commit early, push often, blame the linter occasionally",
    "This window rolls forward · unlike my stash from 2019",
    "Git never forgets · neither does git reflog (thankfully)",
    "Shipped via Actions · battle-tested with caffeine and spite",
    "Merge conflicts build character · or at least patience",
    "Works on GitHub’s graph · YMMV on localhost after lunch",
    "Zero deploy Fridays · nonzero deploy anxiety",
    "Semantic versioning in public · chaotic versioning in branches",
    "The numbers are rounded · the impostor syndrome is exact",
)

_HUMOR_FOOTERS = (
    "robots refresh this; humans refresh the coffee",
    "no merge conflicts were harmed in this render",
    "LGTM if you squint at the y-axis",
    "if it’s green, I’m serene (briefly)",
    "still more reliable than my weather app",
    "compiled with hope, linked with habit",
    "not financial advice; not git advice either",
    "may your CI be green and your pings few",
    "hotfix: personality patch pending",
    "works on my aggregate stats",
)

DEFAULT_USERS = (
    "subhramonyu",
    "privatefnsventures-maker",
    "SubhraFLuke",
)


def token() -> str:
    return os.environ.get("MERGE_STATS_TOKEN") or os.environ.get("GITHUB_TOKEN") or ""


def parse_users() -> list[str]:
    raw = os.environ.get("MERGED_GITHUB_USERS", "").strip()
    if raw:
        users = [u.strip() for u in raw.split(",") if u.strip()]
    else:
        users = list(DEFAULT_USERS)
    seen: set[str] = set()
    out: list[str] = []
    for u in users:
        key = u.lower()
        if key not in seen:
            seen.add(key)
            out.append(u)
    return out


def gql(query: str, variables: dict, tok: str) -> dict:
    body = json.dumps({"query": query, "variables": variables}).encode()
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {tok}",
            "Content-Type": "application/json",
            "User-Agent": "subhramonyu-readme-merged-stats",
            "Accept": "application/vnd.github+json",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode())


def rest_get(path: str, tok: str) -> dict | list:
    url = f"https://api.github.com{path}"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {tok}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "subhramonyu-readme-merged-stats",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode())


def contribution_stats_365(login: str, tok: str) -> tuple[int, int, int]:
    """Returns (commits, pull_requests, calendar_total_activity)."""
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=365)
    q = """
    query($login: String!, $from: DateTime!, $to: DateTime!) {
      user(login: $login) {
        contributionsCollection(from: $from, to: $to) {
          totalCommitContributions
          totalPullRequestContributions
          contributionCalendar { totalContributions }
        }
      }
    }
    """
    variables = {
        "login": login,
        "from": start.strftime("%Y-%m-%dT00:00:00Z"),
        "to": now.strftime("%Y-%m-%dT23:59:59Z"),
    }
    data = gql(q, variables, tok)
    if "errors" in data:
        raise RuntimeError(data["errors"])
    u = data.get("data", {}).get("user")
    if not u:
        return (0, 0, 0)
    coll = u.get("contributionsCollection") or {}
    commits = int(coll.get("totalCommitContributions") or 0)
    prs = int(coll.get("totalPullRequestContributions") or 0)
    cal = coll.get("contributionCalendar") or {}
    activity = int(cal.get("totalContributions") or 0)
    return (commits, prs, activity)


def sum_stars_nonfork(login: str, tok: str) -> int:
    total = 0
    page = 1
    while True:
        path = f"/users/{login}/repos?per_page=100&page={page}&type=owner"
        try:
            repos = rest_get(path, tok)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return 0
            raise
        if not repos:
            break
        for r in repos:
            if r.get("fork"):
                continue
            total += int(r.get("stargazers_count") or 0)
        if len(repos) < 100:
            break
        page += 1
        if page > 50:
            break
    return total


def public_repo_count(login: str, tok: str) -> int:
    try:
        u = rest_get(f"/users/{login}", tok)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return 0
        raise
    return int(u.get("public_repos") or 0)


def fmt_num(n: int) -> str:
    return f"{n:,}"


def escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def pick_humor(
    commits: int, prs: int, activity: int, repos: int, stars: int
) -> tuple[str, str]:
    day = datetime.now(timezone.utc).date().toordinal()
    salt = commits + prs * 3 + activity + repos * 5 + stars * 11
    i_sub = (day + salt) % len(_HUMOR_SUBTITLES)
    i_foot = (day * 17 + salt * 13) % len(_HUMOR_FOOTERS)
    return _HUMOR_SUBTITLES[i_sub], _HUMOR_FOOTERS[i_foot]


def write_svg(
    path: str,
    *,
    commits: int,
    prs: int,
    activity: int,
    repos: int,
    stars: int,
) -> None:
    w, h = 900, 224
    title = "My Git activity"
    subtitle, footer_quip = pick_humor(commits, prs, activity, repos, stars)

    def col(
        cx: int,
        y_num: int,
        y_lbl: int,
        value: str,
        label: str,
        hint: str,
        num_fill: str,
        num_size: int = 30,
    ) -> str:
        return f"""
    <g transform="translate({cx},0)" text-anchor="middle" font-family="ui-sans-serif,system-ui,-apple-system,Segoe UI,Helvetica,Arial,sans-serif">
      <text y="{y_num}" fill="url(#{num_fill})" font-size="{num_size}" font-weight="750">{value}</text>
      <text y="{y_lbl}" fill="#c9d1d9" font-size="12" font-weight="600">{escape(label)}</text>
      <text y="{y_lbl + 14}" fill="#6e7681" font-size="9.5">{escape(hint)}</text>
    </g>"""

    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">
  <defs>
    <linearGradient id="borderGrad" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" style="stop-color:#58a6ff"/>
      <stop offset="45%" style="stop-color:#a371f7"/>
      <stop offset="100%" style="stop-color:#79c0ff"/>
    </linearGradient>
    <linearGradient id="gCommits" x1="0%" y1="0%" x2="0%" y2="100%">
      <stop offset="0%" style="stop-color:#eaf2ff"/><stop offset="100%" style="stop-color:#58a6ff"/>
    </linearGradient>
    <linearGradient id="gPR" x1="0%" y1="0%" x2="0%" y2="100%">
      <stop offset="0%" style="stop-color:#f0e7ff"/><stop offset="100%" style="stop-color:#a371f7"/>
    </linearGradient>
    <linearGradient id="gAct" x1="0%" y1="0%" x2="0%" y2="100%">
      <stop offset="0%" style="stop-color:#cfffdb"/><stop offset="100%" style="stop-color:#3fb950"/>
    </linearGradient>
    <linearGradient id="gRepos" x1="0%" y1="0%" x2="0%" y2="100%">
      <stop offset="0%" style="stop-color:#d8f0ff"/><stop offset="100%" style="stop-color:#388bfd"/>
    </linearGradient>
    <linearGradient id="gStars" x1="0%" y1="0%" x2="0%" y2="100%">
      <stop offset="0%" style="stop-color:#f6ecff"/><stop offset="100%" style="stop-color:#d2a8ff"/>
    </linearGradient>
    <linearGradient id="panel" x1="0%" y1="0%" x2="0%" y2="100%">
      <stop offset="0%" style="stop-color:#161b22"/>
      <stop offset="100%" style="stop-color:#0d1117"/>
    </linearGradient>
    <filter id="shadow" x="-15%" y="-15%" width="130%" height="130%">
      <feDropShadow dx="0" dy="6" stdDeviation="10" flood-color="#000" flood-opacity="0.45"/>
    </filter>
  </defs>
  <rect x="2" y="2" width="{w - 4}" height="{h - 4}" rx="18" ry="18" fill="url(#panel)" stroke="url(#borderGrad)" stroke-width="2" filter="url(#shadow)"/>
  <text x="{w / 2}" y="34" text-anchor="middle" fill="#f0f6fc"
        font-family="ui-sans-serif,system-ui,-apple-system,Segoe UI,Helvetica,Arial,sans-serif"
        font-size="19" font-weight="700" letter-spacing="-0.02em">{escape(title)}</text>
  <text x="{w / 2}" y="56" text-anchor="middle" fill="#8b949e"
        font-family="ui-sans-serif,system-ui,-apple-system,Segoe UI,Helvetica,Arial,sans-serif"
        font-size="11">{escape(subtitle)}</text>
  <line x1="32" y1="68" x2="{w - 32}" y2="68" stroke="#30363d" stroke-width="1" stroke-linecap="round"/>

  <g font-family="ui-sans-serif,system-ui,-apple-system,Segoe UI,Helvetica,Arial,sans-serif">
    {col(150, 108, 134, fmt_num(commits), "Commits", "GitHub-counted · 365d", "gCommits", 36)}
    {col(450, 108, 134, fmt_num(prs), "Pull requests", "authored · same window", "gPR", 36)}
    {col(750, 112, 134, fmt_num(activity), "Total activity", "graph total (issues, reviews, …)", "gAct", 28)}
  </g>

  <line x1="48" y1="162" x2="{w - 48}" y2="162" stroke="#21262d" stroke-width="1"/>

  <g font-family="ui-sans-serif,system-ui,-apple-system,Segoe UI,Helvetica,Arial,sans-serif">
    {col(300, 192, 212, fmt_num(repos), "Public repositories", "combined", "gRepos", 30)}
    {col(600, 192, 212, fmt_num(stars), "Stars", "owned non-fork repos", "gStars", 30)}
  </g>

  <text x="{w / 2}" y="{h - 10}" text-anchor="middle" fill="#484f58"
        font-family="ui-monospace,SFMono-Regular,Menlo,Consolas,monospace" font-size="8.5">
    {escape(f"GitHub Actions · public data · {footer_quip}")}
  </text>
</svg>
'''
    with open(path, "w", encoding="utf-8") as f:
        f.write(svg)


def main() -> int:
    users = parse_users()
    if not users:
        print("No GitHub usernames to merge", file=sys.stderr)
        return 1

    tok = token()
    if not tok:
        print("No GITHUB_TOKEN / MERGE_STATS_TOKEN", file=sys.stderr)
        return 1

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out = os.path.join(root, "merged-stats.svg")

    total_cm = total_pr = total_act = total_repos = total_stars = 0

    try:
        for login in users:
            cm, pr, act = contribution_stats_365(login, tok)
            total_cm += cm
            total_pr += pr
            total_act += act
            total_repos += public_repo_count(login, tok)
            total_stars += sum_stars_nonfork(login, tok)
    except Exception as e:
        print(f"API error: {e}", file=sys.stderr)
        return 1

    write_svg(
        out,
        commits=total_cm,
        prs=total_pr,
        activity=total_act,
        repos=total_repos,
        stars=total_stars,
    )
    print(
        f"Wrote {out} for {len(users)} users: commits={total_cm}, prs={total_pr}, "
        f"activity={total_act}, repos={total_repos}, stars={total_stars}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
