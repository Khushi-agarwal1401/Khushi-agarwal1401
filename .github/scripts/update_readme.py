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

OWNER = os.environ.get("GITHUB_REPOSITORY_OWNER", "").strip()
TOKEN = os.environ.get("GH_TOKEN", "").strip()
README_PATH = "README.md"

START_CURRENTLY = "<!-- START_SECTION:currently -->"
END_CURRENTLY = "<!-- END_SECTION:currently -->"
START_PROJECTS = "<!-- START_SECTION:projects -->"
END_PROJECTS = "<!-- END_SECTION:projects -->"

PROJECT_COUNT = 6  # projects shown in the Featured Projects table
CURRENTLY_REPO_COUNT = 5
MAX_LANGS = 3

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
    repos = fetch_recent_repos(PROJECT_COUNT)
    currently = build_currently_section(repos[:CURRENTLY_REPO_COUNT])
    projects = build_projects_section(OWNER, repos)

    with open(README_PATH, encoding="utf-8") as fh:
        readme = fh.read()

    readme = update_section(readme, START_CURRENTLY, END_CURRENTLY, currently)
    readme = update_section(readme, START_PROJECTS, END_PROJECTS, projects)

    with open(README_PATH, "w", encoding="utf-8") as fh:
        fh.write(readme)

    print("✅ README sections updated:")
    print("--- Currently ---")
    print(currently)
    print("--- Featured Projects (top repos) ---")
    for repo in repos:
        print(f"  - {repo.get('name')}")


if __name__ == "__main__":
    main()
