#!/usr/bin/env python3
"""Auto-updates dynamic sections of the profile README from GitHub API data.

Currently managed sections:

  - "Currently" block, between:
        <!-- START_SECTION:currently --> ... <!-- END_SECTION:currently -->
    Mapping:
      - 🔭 Working on        -> most recently pushed public repo (+ description)
      - 🌱 Learning           -> primary languages of the recent repos
      - 👯 Looking to collab. -> recent repos that have open issues

  - "Featured Projects" table, between:
        <!-- START_SECTION:projects --> ... <!-- END_SECTION:projects -->
    Shows the most recently pushed public repos with live star/fork/language
    badge images.

  - "Tech Stack" section, between:
        <!-- START_SECTION:techstack --> ... <!-- END_SECTION:techstack -->
    Curated skill icons plus auto-detected languages from the public repos
    (new project in a new language -> its icon is added automatically).

  - "Recent GitHub Activity" list, between:
        <!-- START_SECTION:activity --> ... <!-- END_SECTION:activity -->
    Latest meaningful public events (pushes, stars, PRs, issues, forks...) with
    relative timestamps. Events on the profile repo itself are skipped.

Runs inside GitHub Actions; can also be executed locally for testing.
"""

from __future__ import annotations

import html
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

OWNER = os.environ.get("GITHUB_REPOSITORY_OWNER", "").strip()
TOKEN = os.environ.get("GH_TOKEN", "").strip()
README_PATH = "README.md"

START_CURRENTLY = "<!-- START_SECTION:currently -->"
END_CURRENTLY = "<!-- END_SECTION:currently -->"
START_PROJECTS = "<!-- START_SECTION:projects -->"
END_PROJECTS = "<!-- END_SECTION:projects -->"
START_TECHSTACK = "<!-- START_SECTION:techstack -->"
END_TECHSTACK = "<!-- END_SECTION:techstack -->"
START_ACTIVITY = "<!-- START_SECTION:activity -->"
END_ACTIVITY = "<!-- END_SECTION:activity -->"

PROJECT_COUNT = 6  # projects shown in the Featured Projects table
CURRENTLY_REPO_COUNT = 5
MAX_LANGS = 3
TECHSTACK_REPO_LIMIT = 30  # repos scanned for language detection
ACTIVITY_COUNT = 6  # recent-activity items to show

BADGE_STYLE = "style=flat-square"


def api(path: str):
    """GET a GitHub REST endpoint and return the parsed JSON."""
    req = urllib.request.Request(f"https://api.github.com{path}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "profile-readme-updater")
    if TOKEN:
        req.add_header("Authorization", f"Bearer {TOKEN}")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="ignore")
        print(f"GitHub API error ({exc.code}) for {path}: {body}", file=sys.stderr)
        raise
    except urllib.error.URLError as exc:
        print(f"Network error fetching {path}: {exc}", file=sys.stderr)
        raise


def fetch_recent_repos(limit: int) -> list[dict]:
    """Top `limit` public, non-fork repos by most recent push."""
    if not OWNER:
        raise SystemExit("GITHUB_REPOSITORY_OWNER is not set.")

    repos = api(f"/users/{OWNER}/repos?sort=pushed&per_page=100&type=public")
    projects = [
        repo
        for repo in repos
        if not repo.get("fork") and repo.get("name", "").lower() != OWNER.lower()
    ]
    return projects[:limit]


def pretty_name(repo: dict) -> str:
    """'AI-Resume-Builder-and-Analyzer' -> 'AI Resume Builder and Analyzer'."""
    return (
        (repo.get("name") or "")
        .replace("-", " ")
        .replace("_", " ")
        .strip()
        or "a project"
    )


def truncate(text: str, limit: int) -> str:
    """Cut long text at a word boundary."""
    if len(text) <= limit:
        return text
    cut = text[: limit - 1]
    last_space = cut.rfind(" ")
    if last_space > limit // 2:
        return cut[:last_space] + "…"
    return cut.rstrip() + "…"


def sanitize_md(text: str) -> str:
    """Remove characters that could break markdown rendering."""
    return text.replace("`", "'").replace("|", "").strip()


def summarize_repo(repo: dict) -> str:
    name = pretty_name(repo)
    desc = sanitize_md(" ".join((repo.get("description") or "").split()))
    if desc:
        return f"**{name}** — {truncate(desc, 70)}"
    return f"**{name}**"


# ---------------------------------------------------------------- Currently --


def build_currently_section(repos: list[dict]) -> str:
    if not repos:
        return "\n".join(
            [
                "- 🔭 Working on **new projects**",
                "- 🌱 Learning **new technologies**",
                "- 👯 Looking to collaborate on open-source projects",
            ]
        )

    # 🔭 Working on: most recently pushed repo
    working = f"- 🔭 Working on {summarize_repo(repos[0])}"

    # 🌱 Learning: unique primary languages of the recent repos
    langs: list[str] = []
    for repo in repos:
        lang = (repo.get("language") or "").strip()
        if lang and lang not in langs:
            langs.append(lang)
        if len(langs) >= MAX_LANGS:
            break
    if langs:
        learning = f"- 🌱 Learning **{'**, **'.join(langs)}**"
    else:
        learning = "- 🌱 Learning **new technologies**"

    # 👯 Collaborating: recent repos that have open issues
    open_issue_repos = [
        repo for repo in repos if (repo.get("open_issues_count") or 0) > 0
    ]
    if open_issue_repos:
        names = ", ".join(
            f"**{pretty_name(repo)}**" for repo in open_issue_repos[:3]
        )
        collaborating = f"- 👯 Looking to collaborate on {names}"
    else:
        collaborating = "- 👯 Looking to collaborate on open-source projects"

    return "\n".join([working, learning, collaborating])


# ------------------------------------------------------ Recent activity --


def time_ago(iso: str) -> str:
    """'2026-08-04T09:21:54Z' -> '2d ago'."""
    try:
        then = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        seconds = int((datetime.now(timezone.utc) - then).total_seconds())
    except ValueError:
        return "recently"
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    if seconds < 604800:
        return f"{seconds // 86400}d ago"
    if seconds < 2592000:
        return f"{seconds // 604800}w ago"
    return then.strftime("%b %Y")


def fetch_public_events(limit: int = 30) -> list[dict]:
    """Most recent public events for the profile owner."""
    if not OWNER:
        raise SystemExit("GITHUB_REPOSITORY_OWNER is not set.")
    return api(f"/users/{OWNER}/events/public?per_page={limit}")


def activity_line(event: dict) -> str | None:
    """Render a single event as a markdown bullet, or None to skip it."""
    event_type = event.get("type", "")
    repo_full = (event.get("repo") or {}).get("name", "")
    payload = event.get("payload") or {}

    # Skip the profile repo itself (the auto-update bot's own commits are noise)
    if repo_full.lower() == f"{OWNER.lower()}/{OWNER.lower()}":
        return None

    repo_pretty = repo_full.split("/", 1)[-1].replace("-", " ").replace("_", " ").strip()
    repo_link = f"**[{repo_pretty}](https://github.com/{repo_full})**"
    when = time_ago(event.get("created_at", ""))

    if event_type == "PushEvent":
        commits = payload.get("size") or len(payload.get("commits") or [])
        if commits and commits > 1:
            verb = f"Pushed {commits} commits to"
        else:
            verb = "Pushed to"
        return f"- 🚀 {verb} {repo_link} — {when}"
    if event_type == "WatchEvent":
        return f"- ⭐ Starred {repo_link} — {when}"
    if event_type == "ForkEvent":
        return f"- 🍴 Forked {repo_link} — {when}"
    if event_type == "CreateEvent":
        ref_type = payload.get("ref_type", "repository")
        if ref_type == "repository":
            return f"- 🎉 Created {repo_link} — {when}"
        return f"- 🌿 Created a {ref_type} in {repo_link} — {when}"
    if event_type == "ReleaseEvent":
        return f"- 📦 Released a version of {repo_link} — {when}"
    if event_type == "PullRequestEvent":
        action = payload.get("action", "")
        if action == "opened":
            return f"- 🔀 Opened a PR in {repo_link} — {when}"
        if action == "closed":
            merged = (payload.get("pull_request") or {}).get("merged", False)
            return f"- ✅ Merged a PR in {repo_link} — {when}" if merged else f"- 🔀 Closed a PR in {repo_link} — {when}"
        return None
    if event_type == "IssuesEvent":
        action = payload.get("action", "")
        if action == "opened":
            return f"- 🐛 Opened an issue in {repo_link} — {when}"
        if action == "closed":
            return f"- ✅ Closed an issue in {repo_link} — {when}"
        return None
    if event_type == "IssueCommentEvent":
        return f"- 💬 Commented in {repo_link} — {when}"
    if event_type in ("PullRequestReviewEvent", "PullRequestReviewCommentEvent"):
        return f"- 👀 Reviewed a PR in {repo_link} — {when}"
    return None


def build_activity_section(events: list[dict]) -> str:
    """Top meaningful events as a bullet list (deduped by type + repo)."""
    items: list[str] = []
    seen: set[tuple[str, str]] = set()
    for event in events:
        if len(items) >= ACTIVITY_COUNT:
            break
        repo_full = (event.get("repo") or {}).get("name", "")
        key = (event.get("type", ""), repo_full)
        if key in seen:
            continue
        line = activity_line(event)
        if line is None:
            continue
        seen.add(key)
        items.append(line)

    if not items:
        return "- No recent public activity — check back soon!"
    return "\n".join(items)


# ------------------------------------------------------------ Tech stack --

# Curated base skills (things you know that may not show up in public repos)
BASE_SKILLS = {
    "Languages": ["c", "cpp", "java", "js", "python"],
    "Frontend": ["html", "css", "bootstrap", "react"],
    "Backend & Data": ["fastapi", "mysql", "nodejs", "mongodb"],
    "Tools": ["git", "github", "vscode", "linux", "docker", "figma", "vercel", "netlify"],
}

# GitHub API language name -> (skillicons slug, category)
AUTO_LANGS = {
    # Languages
    "TypeScript": ("ts", "Languages"),
    "JavaScript": ("js", "Languages"),
    "Python": ("python", "Languages"),
    "Java": ("java", "Languages"),
    "C": ("c", "Languages"),
    "C++": ("cpp", "Languages"),
    "C#": ("cs", "Languages"),
    "Go": ("go", "Languages"),
    "Rust": ("rust", "Languages"),
    "Ruby": ("ruby", "Languages"),
    "PHP": ("php", "Languages"),
    "Kotlin": ("kotlin", "Languages"),
    "Swift": ("swift", "Languages"),
    "Dart": ("dart", "Languages"),
    "Scala": ("scala", "Languages"),
    "Shell": ("bash", "Languages"),
    "Zig": ("zig", "Languages"),
    "Lua": ("lua", "Languages"),
    "Haskell": ("haskell", "Languages"),
    "Elixir": ("elixir", "Languages"),
    "Perl": ("perl", "Languages"),
    "Objective-C": ("objectivec", "Languages"),
    "Solidity": ("solidity", "Languages"),
    "Assembly": ("assembly", "Languages"),
    "TeX": ("latex", "Languages"),
    # Frontend
    "HTML": ("html", "Frontend"),
    "CSS": ("css", "Frontend"),
    "SCSS": ("sass", "Frontend"),
    "LESS": ("less", "Frontend"),
    "Stylus": ("stylus", "Frontend"),
    "Vue": ("vue", "Frontend"),
    "Svelte": ("svelte", "Frontend"),
    "Astro": ("astro", "Frontend"),
    # Backend & Data
    "SQL": ("sql", "Backend & Data"),
    "PostgreSQL": ("postgres", "Backend & Data"),
    "Jupyter Notebook": ("jupyter", "Backend & Data"),
    "MATLAB": ("matlab", "Backend & Data"),
    "R": ("r", "Backend & Data"),
    # Tools
    "Dockerfile": ("docker", "Tools"),
    "Makefile": ("make", "Tools"),
    "CMake": ("cmake", "Tools"),
    "Vim Script": ("vim", "Tools"),
}


def build_techstack_section(repos: list[dict]) -> str:
    """Curated base skills + languages auto-detected from the user's repos."""
    auto: dict[str, list[str]] = {}
    for repo in repos:
        entry = AUTO_LANGS.get(repo.get("language") or "")
        if not entry:
            continue
        slug, category = entry
        if slug not in auto.setdefault(category, []):
            auto[category].append(slug)

    blocks = []
    for category, base in BASE_SKILLS.items():
        slugs = list(base)
        for slug in auto.get(category, []):
            if slug not in slugs:
                slugs.append(slug)
        blocks.append(
            f"### {category}\n\n"
            '<div align="center">\n\n'
            f'<img src="https://skillicons.dev/icons?i={",".join(slugs)}"/>\n\n'
            "</div>"
        )
    return "\n\n".join(blocks)


# ------------------------------------------------------- Featured projects --


def project_badges(owner: str, name: str) -> str:
    stars = (
        f"https://img.shields.io/github/stars/{owner}/{name}"
        f"?{BADGE_STYLE}&label=Stars&color=E75480"
    )
    forks = (
        f"https://img.shields.io/github/forks/{owner}/{name}"
        f"?{BADGE_STYLE}&label=Forks&color=BF91FF"
    )
    lang = (
        f"https://img.shields.io/github/languages/top/{owner}/{name}"
        f"?{BADGE_STYLE}&label=Language&color=F8D847"
    )
    return (
        f'<img src="{stars}"/>'
        f'<img src="{forks}"/>'
        f'<img src="{lang}"/>'
    )


def project_cell(owner: str, repo: dict) -> str:
    name = repo.get("name", "")
    url = f"https://github.com/{owner}/{name}"
    title = html.escape(pretty_name(repo))
    desc = html.escape(
        truncate(sanitize_md(" ".join((repo.get("description") or "").split())), 80)
    )

    lines = [f'      <a href="{url}"><b>{title}</b></a><br>']
    if desc:
        lines.append(f"      {desc}<br>")
    lines.append(f"      {project_badges(owner, name)}")

    return "    <td align=\"center\">\n" + "\n".join(lines) + "\n    </td>"


def build_projects_section(owner: str, repos: list[dict]) -> str:
    if not repos:
        return "No public projects yet — check back soon!"

    rows = []
    for i in range(0, len(repos), 2):
        cells = [project_cell(owner, repo) for repo in repos[i : i + 2]]
        rows.append("    <tr>\n" + "\n".join(cells) + "\n    </tr>")

    table = "\n".join(rows)
    return (
        '<div align="center">\n\n'
        "<table>\n"
        f"{table}\n"
        "</table>\n\n"
        "</div>"
    )


# ------------------------------------------------------------------ Helpers --


def update_section(readme: str, start: str, end: str, content: str) -> str:
    pattern = re.compile(re.escape(start) + r".*?" + re.escape(end), re.DOTALL)
    if not pattern.search(readme):
        raise SystemExit(
            f"Markers not found in README.md — add {start} … {end} around the section."
        )
    return pattern.sub(f"{start}\n{content}\n{end}", readme, count=1)


def main() -> None:
    repos = fetch_recent_repos(TECHSTACK_REPO_LIMIT)
    currently = build_currently_section(repos[:CURRENTLY_REPO_COUNT])
    projects = build_projects_section(OWNER, repos[:PROJECT_COUNT])
    techstack = build_techstack_section(repos)
    try:
        events = fetch_public_events()
    except Exception as exc:  # don't let a hiccup block the other sections
        print(f"⚠️ Could not fetch recent activity ({exc}); keeping current list.")
        events = []
    activity = build_activity_section(events)

    with open(README_PATH, encoding="utf-8") as fh:
        readme = fh.read()

    readme = update_section(readme, START_CURRENTLY, END_CURRENTLY, currently)
    readme = update_section(readme, START_PROJECTS, END_PROJECTS, projects)
    readme = update_section(readme, START_TECHSTACK, END_TECHSTACK, techstack)
    readme = update_section(readme, START_ACTIVITY, END_ACTIVITY, activity)

    with open(README_PATH, "w", encoding="utf-8") as fh:
        fh.write(readme)

    print("✅ README sections updated:")
    print("--- Currently ---")
    print(currently)
    print("--- Featured Projects (top repos) ---")
    for repo in repos[:PROJECT_COUNT]:
        print(f"  - {repo.get('name')}")
    print("--- Tech Stack (detected languages) ---")
    detected = sorted({repo.get('language') for repo in repos if repo.get('language')})
    print("  " + ", ".join(detected) if detected else "  (none)")
    print("--- Recent Activity ---")
    print(activity)


if __name__ == "__main__":
    main()
