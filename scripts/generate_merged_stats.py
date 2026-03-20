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


def write_svg(
    path: str,
    *,
    users: list[str],
    commits: int,
    prs: int,
    activity: int,
    repos: int,
    stars: int,
) -> None:
    w, h = 900, 258
    n = len(users)
    title = "Combined GitHub activity"
    line1 = f"{n} profiles merged · rolling 365 days"
    mid = (n + 1) // 2
    line_handles_a = " · ".join(f"@{escape(u)}" for u in users[:mid])
    line_handles_b = " · ".join(f"@{escape(u)}" for u in users[mid:])

    hint_merge = f"sum of {n} profiles · 365d"

    def col(
        cx: int,
        y_num: int,
        y_lbl: int,
        value: str,
        label: str,
        hint: str,
        num_fill: str,
    ) -> str:
        return f"""
    <g transform="translate({cx},0)" text-anchor="middle" font-family="ui-sans-serif,system-ui,-apple-system,Segoe UI,Helvetica,Arial,sans-serif">
      <text y="{y_num}" fill="url(#{num_fill})" font-size="30" font-weight="750">{value}</text>
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
    <linearGradient id="gProfiles" x1="0%" y1="0%" x2="0%" y2="100%">
      <stop offset="0%" style="stop-color:#ffe2a8"/><stop offset="100%" style="stop-color:#ffa657"/>
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
  <text x="{w / 2}" y="32" text-anchor="middle" fill="#f0f6fc"
        font-family="ui-sans-serif,system-ui,-apple-system,Segoe UI,Helvetica,Arial,sans-serif"
        font-size="18" font-weight="700" letter-spacing="-0.02em">{escape(title)}</text>
  <text x="{w / 2}" y="50" text-anchor="middle" fill="#8b949e"
        font-family="ui-sans-serif,system-ui,-apple-system,Segoe UI,Helvetica,Arial,sans-serif"
        font-size="11.5">{escape(line1)}</text>
  <text x="{w / 2}" y="66" text-anchor="middle" fill="#6e7681"
        font-family="ui-sans-serif,system-ui,-apple-system,Segoe UI,Helvetica,Arial,sans-serif"
        font-size="10">{line_handles_a}</text>
  <text x="{w / 2}" y="82" text-anchor="middle" fill="#6e7681"
        font-family="ui-sans-serif,system-ui,-apple-system,Segoe UI,Helvetica,Arial,sans-serif"
        font-size="10">{line_handles_b}</text>
  <line x1="32" y1="92" x2="{w - 32}" y2="92" stroke="#30363d" stroke-width="1" stroke-linecap="round"/>

  <g font-family="ui-sans-serif,system-ui,-apple-system,Segoe UI,Helvetica,Arial,sans-serif">
    {col(150, 132, 152, fmt_num(commits), "Commits", hint_merge, "gCommits")}
    {col(450, 132, 152, fmt_num(prs), "Pull requests", "authored · 365d", "gPR")}
    {col(750, 132, 152, fmt_num(activity), "Total activity", "contribution graph total", "gAct")}
  </g>

  <line x1="48" y1="178" x2="{w - 48}" y2="178" stroke="#21262d" stroke-width="1"/>

  <g font-family="ui-sans-serif,system-ui,-apple-system,Segoe UI,Helvetica,Arial,sans-serif">
    {col(150, 212, 232, fmt_num(repos), "Public repositories", "combined", "gRepos")}
    {col(450, 212, 232, str(n), "Profiles", "in this merge", "gProfiles")}
    {col(750, 212, 232, fmt_num(stars), "Stars", "owned non-fork repos", "gStars")}
  </g>

  <text x="{w / 2}" y="{h - 10}" text-anchor="middle" fill="#484f58"
        font-family="ui-monospace,SFMono-Regular,Menlo,Consolas,monospace" font-size="8.5">
    Updated by GitHub Actions · public activity only
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
        users=users,
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
