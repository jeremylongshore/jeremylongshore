#!/usr/bin/env python3
"""Generate the neofetch-style profile card as two SVGs, light and dark.

    python3 scripts/build_card.py            # uses $GITHUB_TOKEN
    python3 scripts/build_card.py --dry-run  # print stats, write nothing

Writes card_light.svg and card_dark.svg. README.md swaps between them with a
<picture> element, because GitHub renders README SVGs inside an <img>, where a
prefers-color-scheme media query in the SVG itself does not apply. Two files is
the only mechanism that actually works there.

That <img> context also means: no scripts, no external stylesheets, no webfonts.
Everything here is inline, and the type stack is generic families that every
renderer already has.

Original implementation. The neofetch-profile *idea* is widely used and free to
borrow; the well-known reference implementation carries no licence at all, so
none of its code is used here. Stats collection, layout, palette and copy are
written from scratch on the Intent Solutions design system.

Every number is fetched live. Nothing is hardcoded, and anything the API will not
give us is omitted rather than estimated -- an absent line beats an invented one.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PORTRAIT = ROOT / "assets" / "portrait.txt"
USER = "jeremylongshore"
API = "https://api.github.com/graphql"

# --- Intent Solutions palette. Blueprint (light) / Graphite (dark). -----------
SKINS = {
    "light": {
        "file": "card_light.svg",
        "paper": "#f3f6f4", "panel": "#eef2ef", "ink": "#161b1d",
        "muted": "#4f5b60", "soft": "#636e72", "rule": "#d3dbd7",
        "accent": "#c94213",   # accent-dark: this paints TEXT, so it needs 4.5:1
        "edge": "#ef5a24",     # signal orange: graphical only
        "link": "#2e5c59",
    },
    "dark": {
        "file": "card_dark.svg",
        "paper": "#111417", "panel": "#191d21", "ink": "#f3f6f4",
        "muted": "#a1a1aa", "soft": "#83838d", "rule": "#2c3034",
        "accent": "#fb923c", "edge": "#fb923c", "link": "#5e9c98",
    },
}

MONO = "ui-monospace,SFMono-Regular,Menlo,Consolas,'Liberation Mono',monospace"

QUERY = """
query($login:String!){
  user(login:$login){
    login name createdAt followers{totalCount} following{totalCount}
    contributionsCollection{
      totalCommitContributions
      restrictedContributionsCount
      totalPullRequestContributions
      totalIssueContributions
    }
    repositories(first:100,ownerAffiliations:OWNER,isFork:false,privacy:PUBLIC,
                 orderBy:{field:STARGAZERS,direction:DESC}){
      totalCount
      nodes{ name stargazerCount primaryLanguage{name} }
    }
  }
}
"""


def graphql(token: str) -> dict:
    request = urllib.request.Request(
        API,
        data=json.dumps({"query": QUERY, "variables": {"login": USER}}).encode(),
        headers={"Authorization": f"bearer {token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.load(response)
    if "errors" in payload:
        raise SystemExit(f"GraphQL error: {payload['errors']}")
    return payload["data"]["user"]


def humanise_age(created: str) -> str:
    start = datetime.fromisoformat(created.replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)
    months = (now.year - start.year) * 12 + (now.month - start.month)
    if now.day < start.day:
        months -= 1
    years, months = divmod(max(months, 0), 12)
    days = (now - start).days
    parts = []
    if years:
        parts.append(f"{years} year{'s' if years != 1 else ''}")
    if months:
        parts.append(f"{months} month{'s' if months != 1 else ''}")
    parts.append(f"{days:,} days total")
    return ", ".join(parts)


def collect(token: str) -> dict:
    user = graphql(token)
    repos = user["repositories"]["nodes"]
    contrib = user["contributionsCollection"]

    languages: dict[str, int] = {}
    for repo in repos:
        language = (repo.get("primaryLanguage") or {}).get("name")
        if language:
            languages[language] = languages.get(language, 0) + 1
    ranked = sorted(languages.items(), key=lambda kv: (-kv[1], kv[0]))

    public_commits = contrib["totalCommitContributions"]
    private_commits = contrib["restrictedContributionsCount"]

    return {
        "login": user["login"],
        "age": humanise_age(user["createdAt"]),
        "followers": user["followers"]["totalCount"],
        "following": user["following"]["totalCount"],
        "repos": user["repositories"]["totalCount"],
        "stars": sum(r["stargazerCount"] for r in repos),
        "top_repos": [(r["name"], r["stargazerCount"]) for r in repos[:4] if r["stargazerCount"]],
        "commits_public": public_commits,
        "commits_private": private_commits,
        "commits_total": public_commits + private_commits,
        "prs": contrib["totalPullRequestContributions"],
        "issues": contrib["totalIssueContributions"],
        "languages": ranked[:5],
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    }


def esc(text: str) -> str:
    return (str(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def rows(stats: dict) -> list[tuple[str, str, str]]:
    """(section | key, value, kind). kind: head / row / rule."""
    langs = "  ".join(f"{name} {count}" for name, count in stats["languages"])
    def short(name: str) -> str:
        return name if len(name) <= 26 else name[:25] + "\u2026"
    top = "   ".join(f"{short(name)} {count:,}" for name, count in stats["top_repos"][:1])
    out: list[tuple[str, str, str]] = [
        (f'{stats["login"]}@github', "", "head"),
        ("", "", "rule"),
        ("Uptime", stats["age"], "row"),
        ("Repos", f'{stats["repos"]:,} public sources', "row"),
        ("Stars", f'{stats["stars"]:,}', "row"),
        ("Followers", f'{stats["followers"]:,}  ·  Following {stats["following"]:,}', "row"),
        ("", "", "gap"),
        ("Commits (12mo)", f'{stats["commits_total"]:,}'
                           f'  ({stats["commits_public"]:,} public'
                           f' + {stats["commits_private"]:,} private)', "row"),
        ("Pull requests", f'{stats["prs"]:,}', "row"),
        ("Issues", f'{stats["issues"]:,}', "row"),
        ("", "", "gap"),
        ("Languages", langs, "row"),
        ("Top repos", top, "row"),
        ("", "", "gap"),
        ("Work", "Intent Solutions  ·  intentsolutions.io", "row"),
        ("Focus", "Claude Code plugins, agent tooling, eval infra", "row"),
        ("Ops", "Self-hosted VPS  ·  Caddy  ·  Docker  ·  borg + B2", "row"),
        ("", "", "gap"),
        ("Contact", "jeremy@intentsolutions.io", "row"),
    ]
    return out


# Layout is font-INDEPENDENT on purpose. Estimating a monospace advance width
# and multiplying by the column count put the portrait straight through the
# stats block: the renderer's actual advance was ~11px where the estimate said
# 6.6. GitHub serves this SVG through an <img>, so the font that resolves is
# whatever the viewer has, and no estimate is safe.
#
# Instead: the portrait is pinned to an exact pixel width with textLength, and
# the stats leader is a dashed <line> between two fixed columns rather than a
# run of "." characters whose width we would have to predict.
ART_W = 320       # px the portrait block occupies, enforced via textLength
LINE_H = 12.6
KEY_W = 132       # px reserved for the key before the leader starts


def render(stats: dict, portrait: list[str], skin: dict) -> str:
    width = 900
    pad = 28
    art_w = ART_W
    col2 = pad + art_w + 48
    value_x = col2 + KEY_W + 26
    art_h = len(portrait) * LINE_H
    body = rows(stats)
    text_h = sum(14 if k == "gap" else 21 for _, _, k in body)
    height = int(max(art_h, text_h) + pad * 2 + 34)

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" '
        f'aria-labelledby="card-title card-desc" font-family="{MONO}">',
        '<title id="card-title">Jeremy Longshore — GitHub profile card</title>',
        f'<desc id="card-desc">An ASCII portrait beside live GitHub statistics: '
        f'{stats["repos"]} public source repositories, {stats["stars"]} stars, '
        f'{stats["followers"]} followers, and {stats["commits_total"]} commits in '
        f'the last twelve months.</desc>',
        f'<rect width="{width}" height="{height}" rx="10" fill="{skin["paper"]}"/>',
        f'<rect x="0.5" y="0.5" width="{width-1}" height="{height-1}" rx="10" '
        f'fill="none" stroke="{skin["rule"]}"/>',
        # The Intent Solutions signature: a short signal-orange rule above a
        # mono, tracked, teal kicker.
        f'<rect x="{pad}" y="{pad}" width="32" height="2" fill="{skin["edge"]}"/>',
        f'<text x="{pad + 44}" y="{pad + 6}" font-size="10" font-weight="600" '
        f'letter-spacing="1.6" fill="{skin["link"]}">INTENT SOLUTIONS</text>',
    ]

    y = pad + 42
    for line in portrait:
        if line.strip():
            parts.append(
                f'<text x="{pad}" y="{y:.1f}" font-size="11" fill="{skin["muted"]}" '
                f'textLength="{art_w}" lengthAdjust="spacingAndGlyphs" '
                f'xml:space="preserve">{esc(line)}</text>'
            )
        y += LINE_H

    y = pad + 42
    for key, value, kind in body:
        if kind == "gap":
            y += 14
            continue
        if kind == "head":
            parts.append(
                f'<text x="{col2}" y="{y:.1f}" font-size="15" font-weight="700" '
                f'fill="{skin["accent"]}">{esc(key)}</text>'
            )
            y += 21
            continue
        if kind == "rule":
            parts.append(
                f'<rect x="{col2}" y="{y-14:.1f}" width="{width - col2 - pad}" height="1" fill="{skin["rule"]}"/>'
            )
            y += 12
            continue
        # Three separately positioned <text> elements, not tspans inside one.
        # Relying on tspan flow put the key and its value on top of each other in
        # one renderer and silently dropped a digit in another; GitHub serves
        # this SVG through an <img>, so we do not get to choose the renderer.
        # Monospace means every column position is computable, so compute it.
        parts.append(
            f'<text x="{col2}" y="{y:.1f}" font-size="12" font-weight="600" '
            f'fill="{skin["ink"]}">{esc(key)}</text>'
        )
        parts.append(
            f'<line x1="{col2 + KEY_W}" y1="{y - 4:.1f}" x2="{value_x - 12}" '
            f'y2="{y - 4:.1f}" stroke="{skin["rule"]}" stroke-width="1" '
            f'stroke-dasharray="1 3"/>'
        )
        parts.append(
            f'<text x="{value_x}" y="{y:.1f}" font-size="12" '
            f'fill="{skin["muted"]}">{esc(value)}</text>'
        )
        y += 21

    parts.append(
        f'<text x="{pad}" y="{height - 18}" font-size="9.5" fill="{skin["soft"]}">'
        f'regenerated {esc(stats["generated"])} · commit counts cover the last 12 months'
        f'</text>'
    )
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        raise SystemExit("set GITHUB_TOKEN (needs read:user; classic token for private counts)")

    stats = collect(token)
    if args.dry_run:
        print(json.dumps(stats, indent=2))
        return 0

    if not PORTRAIT.is_file():
        raise SystemExit(f"missing portrait at {PORTRAIT}")
    portrait = PORTRAIT.read_text(encoding="utf-8").rstrip("\n").split("\n")

    for name, skin in SKINS.items():
        target = ROOT / skin["file"]
        target.write_text(render(stats, portrait, skin), encoding="utf-8")
        print(f"wrote {target.relative_to(ROOT)}  ({name})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
