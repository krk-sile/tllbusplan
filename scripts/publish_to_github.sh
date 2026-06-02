#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: ./scripts/publish_to_github.sh <owner/repo> <tag> [remote-name] [fallback-branch]

Example:
  ./scripts/publish_to_github.sh siled/busplan v1.2.6

What it does:
1. Builds package `dist/tallinn_widgets-<version>.tar.gz` (and checksum) for the tag.
2. Ensures git remote points to GitHub for the given repo.
3. Pushes current branch and the release tag.
EOF
}

if [[ "${1-}" == "-h" || "${1-}" == "--help" || $# -lt 2 ]]; then
  usage
  exit 0
fi

OWNER_REPO="$1"
TAG="$2"
REMOTE_NAME="${3:-${GIT_REMOTE:-origin}}"
FALLBACK_BRANCH="${4:-main}"
EXPECTED_URL="git@github.com:${OWNER_REPO}.git"
PUSH_TOKEN="${GITHUB_TOKEN:-${GH_TOKEN:-${GITHUB_PAT:-${GH_PAT:-}}}}"
ORIGINAL_REMOTE_URL=""
RESTORE_REMOTE_URL=0

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

if [[ -n "$(git -C "$PROJECT_ROOT" status --short)" ]]; then
  echo "warning: working tree contains uncommitted changes. they will be included in the pushed commit only if committed first." >&2
fi

if ! git -C "$PROJECT_ROOT" rev-parse -q --verify "$TAG" >/dev/null 2>&1; then
  git -C "$PROJECT_ROOT" tag -a "$TAG" -m "Release ${TAG}"
fi

if ! git -C "$PROJECT_ROOT" remote get-url "$REMOTE_NAME" >/dev/null 2>&1; then
  git -C "$PROJECT_ROOT" remote add "$REMOTE_NAME" "$EXPECTED_URL"
else
  EXISTING_URL="$(git -C "$PROJECT_ROOT" remote get-url "$REMOTE_NAME")"
  ORIGINAL_REMOTE_URL="$EXISTING_URL"
  RESTORE_REMOTE_URL=1
  if [[ "$EXISTING_URL" != *"github.com"* || "$EXISTING_URL" != *"${OWNER_REPO}"* ]]; then
    echo "warning: remote '$REMOTE_NAME' currently points to '${EXISTING_URL}'. Repointing to ${EXPECTED_URL}." >&2
    git -C "$PROJECT_ROOT" remote set-url "$REMOTE_NAME" "$EXPECTED_URL"
  fi
fi

restore_remote_url() {
  if [[ "$RESTORE_REMOTE_URL" -eq 1 && -n "$ORIGINAL_REMOTE_URL" ]]; then
    git -C "$PROJECT_ROOT" remote set-url "$REMOTE_NAME" "$ORIGINAL_REMOTE_URL"
  fi
}

restore_https_remote() {
  if [[ -n "$ORIGINAL_REMOTE_URL" ]]; then
    git -C "$PROJECT_ROOT" remote set-url "$REMOTE_NAME" "$ORIGINAL_REMOTE_URL"
  else
    git -C "$PROJECT_ROOT" remote set-url "$REMOTE_NAME" "$EXPECTED_URL"
  fi
}

push_with_auth_fallback() {
  local ref=$1
  local attempt_output attempt_status
  attempt_output="$(mktemp)"

  set +e
  git -C "$PROJECT_ROOT" push "$REMOTE_NAME" "$ref" >"$attempt_output" 2>&1
  attempt_status=$?
  set -e

  if [[ $attempt_status -eq 0 ]]; then
    return 0
  fi

  if [[ -n "$PUSH_TOKEN" ]] && grep -qE "Permission denied .*publickey|Authentication failed" "$attempt_output"; then
    local https_url="https://x-access-token:${PUSH_TOKEN}@github.com/${OWNER_REPO}.git"
    git -C "$PROJECT_ROOT" remote set-url "$REMOTE_NAME" "$https_url"

    set +e
    git -C "$PROJECT_ROOT" push "$REMOTE_NAME" "$ref" >>"$attempt_output" 2>&1
    attempt_status=$?
    set -e

    if [[ $attempt_status -eq 0 ]]; then
      restore_https_remote
      return 0
    fi
  fi

  echo "error: failed to push ${ref}." >&2
  cat "$attempt_output" >&2
  return 1
}

fetch_with_auth_fallback() {
  local attempt_output attempt_status
  attempt_output="$(mktemp)"

  set +e
  git -C "$PROJECT_ROOT" fetch "$REMOTE_NAME" --tags >"$attempt_output" 2>&1
  attempt_status=$?
  set -e

  if [[ $attempt_status -eq 0 ]]; then
    return 0
  fi

  if [[ -n "$PUSH_TOKEN" ]] && grep -qE "Permission denied .*publickey|Authentication failed" "$attempt_output"; then
    local https_url="https://x-access-token:${PUSH_TOKEN}@github.com/${OWNER_REPO}.git"
    git -C "$PROJECT_ROOT" remote set-url "$REMOTE_NAME" "$https_url"

    set +e
    git -C "$PROJECT_ROOT" fetch "$REMOTE_NAME" --tags >>"$attempt_output" 2>&1
    attempt_status=$?
    set -e

    if [[ $attempt_status -eq 0 ]]; then
      restore_https_remote
      return 0
    fi
  fi

  echo "error: failed to fetch tags from ${REMOTE_NAME}." >&2
  cat "$attempt_output" >&2
  return 1
}

trap 'restore_remote_url' EXIT INT TERM

fetch_with_auth_fallback
CURRENT_BRANCH="$(git -C "$PROJECT_ROOT" rev-parse --abbrev-ref HEAD)"
if [[ "$CURRENT_BRANCH" == "HEAD" ]]; then
  CURRENT_BRANCH="$FALLBACK_BRANCH"
fi
if ! git -C "$PROJECT_ROOT" show-ref --verify --quiet "refs/heads/${CURRENT_BRANCH}"; then
  echo "error: cannot determine branch to push (detached HEAD, fallback '${CURRENT_BRANCH}' missing)." >&2
  exit 1
fi
push_with_auth_fallback "$CURRENT_BRANCH"

if ! git -C "$PROJECT_ROOT" ls-remote --heads "$REMOTE_NAME" | grep -q "refs/heads/${CURRENT_BRANCH}"; then
  echo "error: remote '${REMOTE_NAME}' has no branch refs after push; release creation will fail on empty repo." >&2
  exit 1
fi
push_with_auth_fallback "$TAG"

"$SCRIPT_DIR/package_tallinn_widgets.sh" "${TAG#v}"
PACKAGE_PATH="$(ls -1 "$PROJECT_ROOT/dist/tallinn_widgets-${TAG#v}.tar.gz")"

echo "Published source to $REMOTE_NAME and created tag $TAG"
echo "Package artifact ready at: $PACKAGE_PATH"
echo "Attach package assets in a GitHub release for ${OWNER_REPO}."
