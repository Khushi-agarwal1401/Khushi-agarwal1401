#!/usr/bin/env bash
#
# Weekly off-site backup: mirrors every public GitHub repo (full history,
# all branches + tags) to private repos on Codeberg.
#
# Requires GitHub Actions secrets:
#   CODEBERG_USERNAME  - your Codeberg username
#   CODEBERG_TOKEN     - Codeberg access token (scope: write:repository)
#
# Skips forks and the profile repo itself. Creates any missing Codeberg
# repos (private) via the Codeberg API before mirror-pushing.
set -euo pipefail

OWNER="${GITHUB_REPOSITORY_OWNER:-${GITHUB_OWNER:-}}"
CB_USER="${CODEBERG_USERNAME:-}"
CB_TOKEN="${CODEBERG_TOKEN:-}"
GH_TOKEN="${GH_TOKEN:-}"

if [[ -z "$OWNER" ]]; then
  echo "::error::GITHUB_REPOSITORY_OWNER is not set" >&2
  exit 1
fi
if [[ -z "$CB_USER" || -z "$CB_TOKEN" ]]; then
  echo "::error::CODEBERG_USERNAME / CODEBERG_TOKEN secrets are not set" >&2
  exit 1
fi

CB_API="https://codeberg.org/api/v1"

# Optional GitHub token (workflow provides it) avoids the 60/hr anonymous limit.
API_AUTH=()
if [[ -n "$GH_TOKEN" ]]; then
  API_AUTH=(-H "Authorization: Bearer ${GH_TOKEN}")
fi

echo "==> Listing public repos of ${OWNER} (excluding forks and the profile repo)"
REPO_JSON="$(curl -fsS "${API_AUTH[@]}" "https://api.github.com/users/${OWNER}/repos?per_page=100&type=public")" || {
  echo "::error::GitHub API call failed (rate limit?) — no backups performed" >&2
  exit 1
}
REPOS=()
while IFS= read -r repo; do
  REPOS+=("$repo")
done < <(python3 -c "import sys, json; o='${OWNER}'.lower(); [print(r['name']) for r in json.loads(sys.stdin.read()) if not r['fork'] and r['name'].lower() != o]" <<< "$REPO_JSON")

if [[ ${#REPOS[@]} -eq 0 ]]; then
  echo "No repos to back up."
  exit 0
fi

echo "==> Backing up ${#REPOS[@]} repos to codeberg.org/${CB_USER}"
ok=0
failed=0
for repo in "${REPOS[@]}"; do
  echo "--> ${repo}"

  # Ensure the Codeberg repo exists (private); create it if missing.
  if ! curl -fsS -o /dev/null "${CB_API}/repos/${CB_USER}/${repo}" -H "Authorization: token ${CB_TOKEN}"; then
    if curl -fsS -X POST "${CB_API}/user/repos" \
        -H "Authorization: token ${CB_TOKEN}" \
        -H "Content-Type: application/json" \
        -d "{\"name\":\"${repo}\",\"private\":true,\"description\":\"Automated weekly backup of github.com/${OWNER}/${repo}\"}" >/dev/null; then
      echo "    created private Codeberg repo"
    else
      echo "::error::could not create Codeberg repo '${repo}', skipping" >&2
      failed=$((failed + 1))
      continue
    fi
  fi

  # Mirror-clone from GitHub and mirror-push to Codeberg (full history).
  tmp="/tmp/backup-${repo}.git"
  rm -rf "$tmp"
  if ! git clone --mirror --quiet "https://github.com/${OWNER}/${repo}.git" "$tmp"; then
    echo "::error::clone of '${repo}' failed, skipping" >&2
    failed=$((failed + 1))
    continue
  fi

  if [[ "$(git -C "$tmp" for-each-ref | wc -l | tr -d ' ')" -eq 0 ]]; then
    echo "    repo is empty (no refs); nothing to push"
    rm -rf "$tmp"
    continue
  fi

  # Push without embedding the token in the URL (uses an inline credential helper).
  if git -C "$tmp" \
      -c "credential.helper=!f() { echo username=${CB_USER}; echo password=${CB_TOKEN}; }; f" \
      push --mirror "https://codeberg.org/${CB_USER}/${repo}.git" >/dev/null 2>&1; then
    echo "    backed up"
    ok=$((ok + 1))
  else
    echo "::error::mirror push of '${repo}' failed, skipping" >&2
    failed=$((failed + 1))
  fi
  rm -rf "$tmp"
done

if [[ "$failed" -gt 0 ]]; then
  echo "::warning::Backup incomplete: ${ok} ok, ${failed} failed (see errors above)" >&2
  exit 1
fi
echo "==> Done: ${ok}/${#REPOS[@]} repos backed up to Codeberg"
