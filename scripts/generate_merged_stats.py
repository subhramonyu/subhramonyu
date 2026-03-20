#!/usr/bin/env python3
"""
Build merged-stats.svg from two GitHub usernames (public API).
Uses GraphQL for contribution totals in the last 365 days; REST for star counts.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone


def token() -> str:
    return os.environ.get("MERGE_STATS_TOKEN") or os.environ.get("GITHUB_TOKEN") or ""


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


def contributions_365(login: str, tok: str) -> int:
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=365)
    q = """
    query($login: String!, $from: DateTime!, $to: DateTime!) {
      user(login: $login) {
        contributionsCollection(from: $from, to: $to) {
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
        return 0
    cal = u.get("contributionsCollection", {}).get("contributionCalendar") or {}
    return int(cal.get("totalContributions") or 0)


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
    primary: str,
    alt: str,
    contrib: int,
    repos: int,
    stars: int,
) -> None:
    w, h = 820, 200
    title = "Combined GitHub activity"
    subtitle = f"@{escape(primary)}  +  @{escape(alt)}  ·  last 365 days (contributions)"
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">
  <defs>
    <linearGradient id="g" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" style="stop-color:#58a6ff;stop-opacity:1" />
      <stop offset="55%" style="stop-color:#a371f7;stop-opacity:1" />
      <stop offset="100%" style="stop-color:#79c0ff;stop-opacity:1" />
    </linearGradient>
    <filter id="shadow" x="-20%" y="-20%" width="140%" height="140%">
      <feDropShadow dx="0" dy="4" stdDeviation="8" flood-color="#000" flood-opacity="0.35"/>
    </filter>
  </defs>
  <rect x="1.5" y="1.5" width="{w - 3}" height="{h - 3}" rx="16" ry="16"
        fill="#0d1117" stroke="url(#g)" stroke-width="2" filter="url(#shadow)"/>
  <text x="{w/2}" y="38" text-anchor="middle" fill="#e6edf3"
        font-family="ui-sans-serif,system-ui,-apple-system,Segoe UI,Helvetica,Arial,sans-serif"
        font-size="17" font-weight="650">{escape(title)}</text>
  <text x="{w/2}" y="60" text-anchor="middle" fill="#8b949e"
        font-family="ui-sans-serif,system-ui,-apple-system,Segoe UI,Helvetica,Arial,sans-serif"
        font-size="11.5">{subtitle}</text>
  <g font-family="ui-sans-serif,system-ui,-apple-system,Segoe UI,Helvetica,Arial,sans-serif">
    <g transform="translate(48,95)">
      <text x="0" y="0" fill="#58a6ff" font-size="28" font-weight="700">{fmt_num(contrib)}</text>
      <text x="0" y="22" fill="#8b949e" font-size="11">Contributions</text>
    </g>
    <g transform="translate(248,95)">
      <text x="0" y="0" fill="#79c0ff" font-size="28" font-weight="700">{fmt_num(repos)}</text>
      <text x="0" y="22" fill="#8b949e" font-size="11">Public repos</text>
    </g>
    <g transform="translate(448,95)">
      <text x="0" y="0" fill="#d2a8ff" font-size="28" font-weight="700">{fmt_num(stars)}</text>
      <text x="0" y="22" fill="#8b949e" font-size="11">Stars (owned)</text>
    </g>
    <g transform="translate(648,95)">
      <text x="0" y="0" fill="#7ee787" font-size="28" font-weight="700">2</text>
      <text x="0" y="22" fill="#8b949e" font-size="11">Profiles</text>
    </g>
  </g>
  <text x="{w/2}" y="{h - 18}" text-anchor="middle" fill="#484f58"
        font-family="ui-monospace,SFMono-Regular,Menlo,Consolas,monospace" font-size="9">
    Auto-updated via GitHub Actions · public data only
  </text>
</svg>
'''
    with open(path, "w", encoding="utf-8") as f:
        f.write(svg)


def main() -> int:
    primary = os.environ.get("PRIMARY_GH_USER", "subhramonyu").strip()
    alt = os.environ.get("ALT_GITHUB_USERNAME", "fnsventures").strip() or "fnsventures"
    tok = token()
    if not tok:
        print("No GITHUB_TOKEN / MERGE_STATS_TOKEN", file=sys.stderr)
        return 1

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out = os.path.join(root, "merged-stats.svg")

    try:
        c1 = contributions_365(primary, tok)
        c2 = contributions_365(alt, tok)
        r1 = public_repo_count(primary, tok)
        r2 = public_repo_count(alt, tok)
        s1 = sum_stars_nonfork(primary, tok)
        s2 = sum_stars_nonfork(alt, tok)
    except Exception as e:
        print(f"API error: {e}", file=sys.stderr)
        return 1

    write_svg(
        out,
        primary=primary,
        alt=alt,
        contrib=c1 + c2,
        repos=r1 + r2,
        stars=s1 + s2,
    )
    print(f"Wrote {out}: contrib={c1+c2}, repos={r1+r2}, stars={s1+s2}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
