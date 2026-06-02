#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: ./scripts/publish_to_gitea.sh <owner/repo> <tag> [remote-name] [fallback-branch]

Example:
  ./scripts/publish_to_gitea.sh siled/busplan v1.0.0

What it does:
1. Builds package `dist/tallinn_widgets-<version>.tar.gz` (and checksum) for the tag.
2. Ensures git remote points to git.nlf.gg for the given repo.
3. Pushes current branch and the release tag.

Set GIT_REMOTE (optional, default: origin),
set GITEA_HOST (optional, default: git.nlf.gg) if your server differs.
EOF
}

if [[ "${1-}" == "-h" || "${1-}" == "--help" || $# -lt 2 ]]; then
  usage
  exit 0
fi

OWNER_REPO="$1"
TAG="$2"
REMOTE_NAME="${3:-${GIT_REMOTE:-origin}}"
HOST="${GITEA_HOST:-git.nlf.gg}"
FALLBACK_BRANCH="${4:-main}"
EXPECTED_URL="git@${HOST}:${OWNER_REPO}.git"

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
  if [[ "$EXISTING_URL" != *"$HOST"* || "$EXISTING_URL" != *"${OWNER_REPO}"* ]]; then
    echo "warning: remote '$REMOTE_NAME' currently points to '${EXISTING_URL}'. Repointing to ${EXPECTED_URL}." >&2
    git -C "$PROJECT_ROOT" remote set-url "$REMOTE_NAME" "$EXPECTED_URL"
  fi
fi

git -C "$PROJECT_ROOT" fetch "$REMOTE_NAME" --tags
CURRENT_BRANCH="$(git -C "$PROJECT_ROOT" rev-parse --abbrev-ref HEAD)"
if [[ "$CURRENT_BRANCH" == "HEAD" ]]; then
  CURRENT_BRANCH="$FALLBACK_BRANCH"
fi
if ! git -C "$PROJECT_ROOT" show-ref --verify --quiet "refs/heads/${CURRENT_BRANCH}"; then
  echo "error: cannot determine branch to push (detached HEAD, fallback '${CURRENT_BRANCH}' missing)." >&2
  exit 1
fi
git -C "$PROJECT_ROOT" push "$REMOTE_NAME" "$CURRENT_BRANCH"
if ! git -C "$PROJECT_ROOT" ls-remote --heads "$REMOTE_NAME" | grep -q "refs/heads/${CURRENT_BRANCH}"; then
  echo "error: remote '${REMOTE_NAME}' has no branch refs after push; release creation will fail on empty repo." >&2
  exit 1
fi
git -C "$PROJECT_ROOT" push "$REMOTE_NAME" "$TAG"

./scripts/package_tallinn_widgets.sh "${TAG#v}"
PACKAGE_PATH="$(ls -1 "$PROJECT_ROOT/dist/tallinn_widgets-${TAG#v}.tar.gz")"

echo "Published source to $REMOTE_NAME and created tag $TAG"
echo "Package artifact ready at: $PACKAGE_PATH"
echo "Attach package artifact in a Gitea release for $OWNER_REPO and commit the same manifest if needed."
