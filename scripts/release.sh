#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: ./scripts/release.sh [OPTIONS] <tag-or-version> [owner/repo]

Options:
  --allow-dirty         Allow release run with local uncommitted changes.
  --skip-publish        Skip branch/tag push to origin.
  --no-release-assets   Build and publish code, but skip backend release/assets upload.
  --remote <name>       Remote name to use for publish (overrides backend default).
  --backend <gitea|github>
                       Choose backend for publish/release operations.
                       Default: from PUBLISH_BACKEND (or gitea).
  --help                Show this help.

Environment:
  PUBLISH_BACKEND       Optional default backend: gitea or github.
  PUBLISH_REMOTE       Optional default remote name.
  GITEA_REMOTE         Optional Gitea remote name override.
  GITHUB_REMOTE        Optional GitHub remote name override.
  GITEA_TOKEN          Optional API token for auto release and asset upload.
  GITEA_HOST           Base host (default: git.nlf.gg)
  GITEA_OWNER_REPO     Optional default owner/repo.
  GITEA_API_URL        Optional API base URL (defaults to https://<host>/api/v1)
  GITHUB_TOKEN         Optional GitHub API token for release upload.
  GH_TOKEN             Optional GitHub API token for release upload.
  GH_PAT               Optional GitHub PAT for release upload.
  GITHUB_PAT           Optional GitHub PAT for release upload.
  GITHUB_OWNER_REPO    Optional default owner/repo for GitHub backend.
  GITHUB_FALLBACK_BRANCH  Branch pushed when HEAD is detached (default main).
  GITEA_FALLBACK_BRANCH   Branch pushed when HEAD is detached (default main).

Examples:
  ./scripts/release.sh v1.2.5
  ./scripts/release.sh --backend github v1.2.6 siled/busplan
  GITHUB_TOKEN=... ./scripts/release.sh --backend github 1.2.6 siled/busplan
  # owner/repo before tag is also supported
  ./scripts/release.sh --backend github krk-sile/tllbusplan v1.2.7
  # target a specific remote explicitly
  ./scripts/release.sh --backend github --remote github --allow-dirty v1.2.7 krk-sile/tllbusplan
EOF
}

ALLOW_DIRTY=0
SKIP_PUBLISH=0
SKIP_ASSETS=0
TAG_INPUT=""
OWNER_REPO=""
BACKEND=""
REMOTE_NAME=""
FALLBACK_BRANCH=""

is_repo_id() {
  local candidate=$1
  [[ "$candidate" == */* && "$candidate" != */ && "$candidate" != */.git ]]
}

while [[ $# -gt 0 ]]; do
  case "${1-}" in
    --allow-dirty)
      ALLOW_DIRTY=1
      ;;
    --skip-publish)
      SKIP_PUBLISH=1
      ;;
    --no-release-assets)
      SKIP_ASSETS=1
      ;;
    --remote)
      REMOTE_NAME="${2-}"
      if [[ -z "$REMOTE_NAME" ]]; then
        echo "error: --remote expects a remote name." >&2
        usage >&2
        exit 1
      fi
      shift
      ;;
    --backend)
      BACKEND="${2-}"
      if [[ -z "$BACKEND" ]]; then
        echo "error: --backend expects 'gitea' or 'github'" >&2
        usage >&2
        exit 1
      fi
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    --*)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
    *)
      if is_repo_id "$1" && [[ -z "$OWNER_REPO" ]]; then
        OWNER_REPO="$1"
      elif [[ -z "$TAG_INPUT" ]]; then
        TAG_INPUT="$1"
      elif [[ -z "$OWNER_REPO" ]]; then
        OWNER_REPO="$1"
      else
        echo "Too many arguments." >&2
        usage >&2
        exit 1
      fi
      ;;
  esac
  shift
done

if [[ -z "$TAG_INPUT" ]]; then
  echo "error: missing tag/version" >&2
  usage >&2
  exit 1
fi

VERSION="${TAG_INPUT#v}"
TAG="v${VERSION}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

if [[ -f "$PROJECT_ROOT/.env" ]]; then
  # shellcheck disable=SC1090
  set -a
  source "$PROJECT_ROOT/.env"
  set +a
fi

MANIFEST_PATH="$PROJECT_ROOT/custom_components/tallinn_widgets/manifest.json"
if [[ ! -f "$MANIFEST_PATH" ]]; then
  echo "error: manifest not found at $MANIFEST_PATH" >&2
  exit 1
fi

BACKEND="${BACKEND:-${PUBLISH_BACKEND:-gitea}}"
if [[ "$BACKEND" != "gitea" && "$BACKEND" != "github" ]]; then
  echo "error: unsupported backend '$BACKEND'. use gitea or github." >&2
  exit 1
fi

if [[ -z "$OWNER_REPO" ]]; then
  if [[ "$BACKEND" == "github" ]]; then
    OWNER_REPO="${GITHUB_OWNER_REPO:-${GITHUB_REPO:-${GITEA_OWNER_REPO:-${GITEA_REPO:-siled/busplan}}}}"
  else
    OWNER_REPO="${GITEA_OWNER_REPO:-${GITEA_REPO:-${GITHUB_OWNER_REPO:-${GITHUB_REPO:-siled/busplan}}}}"
  fi
fi

if [[ -z "$REMOTE_NAME" ]]; then
  if [[ "$BACKEND" == "github" ]]; then
    REMOTE_NAME="${GITHUB_REMOTE:-${PUBLISH_REMOTE:-github}}"
    FALLBACK_BRANCH="${GITHUB_FALLBACK_BRANCH:-main}"
  else
    REMOTE_NAME="${GITEA_REMOTE:-${PUBLISH_REMOTE:-origin}}"
    FALLBACK_BRANCH="${GITEA_FALLBACK_BRANCH:-main}"
  fi
fi

if [[ -z "$FALLBACK_BRANCH" ]]; then
  FALLBACK_BRANCH="main"
fi

remote_has_heads() {
  local remote_name=$1
  local refs

  if ! refs="$(git -C "$PROJECT_ROOT" ls-remote --heads "$remote_name" 2>/dev/null || true)"; then
    return 1
  fi
  if [[ -z "$(echo "$refs" | tr -d '[:space:]')" ]]; then
    return 2
  fi
  return 0
}

remote_has_heads_with_token_fallback() {
  local remote_name=$1
  local token

  if remote_has_heads "$remote_name"; then
    return 0
  fi

  if [[ "$BACKEND" == "github" ]]; then
    token="${GITHUB_TOKEN:-${GH_TOKEN:-${GH_PAT:-${GITHUB_PAT:-}}}}"
    if [[ -n "$token" ]]; then
      local https_refs
      local https_remote="https://x-access-token:${token}@github.com/${OWNER_REPO}.git"
      if https_refs="$(git -C "$PROJECT_ROOT" ls-remote --heads "$https_remote" 2>/dev/null || true)"; then
        if [[ -n "$(echo "$https_refs" | tr -d '[:space:]')" ]]; then
          return 0
        fi
      fi
    fi
  fi

  return 1
}

GITEA_HOST="${GITEA_HOST:-git.nlf.gg}"
GITEA_API="${GITEA_API_URL:-https://${GITEA_HOST}/api/v1}"

if [[ $ALLOW_DIRTY -eq 0 && -n "$(git -C "$PROJECT_ROOT" status --short)" ]]; then
  echo "error: working tree has uncommitted changes. Use --allow-dirty if intentional." >&2
  git -C "$PROJECT_ROOT" status --short
  exit 1
fi

echo "Release target:"
echo "  backend:  ${BACKEND}"
echo "  repo:     ${OWNER_REPO}"
echo "  remote:   ${REMOTE_NAME}"
echo "  branch:   ${FALLBACK_BRANCH} (fallback if detached)"

cp "$PROJECT_ROOT/tallinn_widgets/scripts/tallinn_widget_lib.py" \
  "$PROJECT_ROOT/custom_components/tallinn_widgets/tallinn_widget_lib.py"

python3 - "$MANIFEST_PATH" "$VERSION" <<'PY'
import json
import sys

manifest_path, version = sys.argv[1], sys.argv[2]

with open(manifest_path, "r", encoding="utf-8") as file:
    manifest = json.load(file)

manifest["version"] = version

with open(manifest_path, "w", encoding="utf-8") as file:
    json.dump(manifest, file, indent=2)
    file.write("\n")
PY

git -C "$PROJECT_ROOT" add \
  custom_components/tallinn_widgets/tallinn_widget_lib.py \
  custom_components/tallinn_widgets/manifest.json \
  scripts/package_tallinn_widgets.sh \
  scripts/publish_to_github.sh \
  scripts/publish_to_gitea.sh \
  scripts/release.sh \
  scripts/install_tallinn_widgets.sh \
  hacs.json \
  .gitignore \
  README.md > /dev/null 2>&1 || true
if ! git -C "$PROJECT_ROOT" diff --cached --quiet; then
  git -C "$PROJECT_ROOT" commit -m "chore(release): bump version ${TAG}" > /dev/null
fi
git -C "$PROJECT_ROOT" reset HEAD --quiet

"$SCRIPT_DIR/package_tallinn_widgets.sh" "$VERSION"

if [[ $SKIP_PUBLISH -eq 0 ]]; then
  if [[ "$BACKEND" == "github" ]]; then
    "$SCRIPT_DIR/publish_to_github.sh" "$OWNER_REPO" "$TAG" "$REMOTE_NAME" "$FALLBACK_BRANCH"
  else
    "$SCRIPT_DIR/publish_to_gitea.sh" "$OWNER_REPO" "$TAG" "$REMOTE_NAME" "$FALLBACK_BRANCH"
  fi
fi

if ! remote_has_heads_with_token_fallback "$REMOTE_NAME"; then
  echo "error: remote '${REMOTE_NAME}' appears to have no branch refs after publish step." >&2
  echo "       Push a real branch on first run and then retry:" >&2
  echo "       git push ${REMOTE_NAME} ${FALLBACK_BRANCH}" >&2
  exit 1
fi

if [[ $SKIP_ASSETS -eq 1 ]]; then
  echo "Skipping release-assets upload (--no-release-assets)."
  echo "Package artifacts:
- $PROJECT_ROOT/dist/tallinn_widgets-${VERSION}.zip
- $PROJECT_ROOT/dist/tallinn_widgets-${VERSION}.tar.gz"
  exit 0
fi

json_field() {
  local file=$1
  local key=$2
  python3 - "$file" "$key" <<'PY'
import json
import sys

with open(sys.argv[1], "r", encoding="utf-8") as file:
    payload = json.load(file)

print(payload.get(sys.argv[2], ""))
PY
}

if [[ "$BACKEND" == "github" ]]; then
  ZIP_PATH="$PROJECT_ROOT/dist/tallinn_widgets-${VERSION}.zip"
  TAR_PATH="$PROJECT_ROOT/dist/tallinn_widgets-${VERSION}.tar.gz"
  GITHUB_TOKEN="${GITHUB_TOKEN:-${GH_TOKEN:-${GH_PAT:-${GITHUB_PAT:-}}}}"
  GITHUB_API="https://api.github.com"

  if [[ -z "${GITHUB_TOKEN:-}" ]]; then
    echo "No GitHub token set (GITHUB_TOKEN/GH_TOKEN/GH_PAT/GITHUB_PAT). Skipping auto release/upload." >&2
    echo "Create a GitHub release for ${TAG} and upload:"
    echo "- $ZIP_PATH"
    if [[ -f "$TAR_PATH" ]]; then
      echo "- $TAR_PATH"
    fi
    exit 0
  fi

  if [[ ! -f "$ZIP_PATH" ]]; then
    echo "error: expected release artifact not found: $ZIP_PATH" >&2
    exit 1
  fi

  release_lookup="$(mktemp)"
  lookup_status="$(curl -sS -o "$release_lookup" -w '%{http_code}' -H "Authorization: Bearer ${GITHUB_TOKEN}" \
    -H "Accept: application/vnd.github+json" \
    -H "X-GitHub-Api-Version: 2022-11-28" \
    "$GITHUB_API/repos/${OWNER_REPO}/releases/tags/${TAG}")"

  RELEASE_ID=""
  UPLOAD_URL=""
  if [[ "$lookup_status" == "200" ]]; then
    RELEASE_ID="$(json_field "$release_lookup" id)"
    UPLOAD_URL="$(json_field "$release_lookup" upload_url | sed 's/{.*$//')"
  else
    release_body_file="$(mktemp)"
    cat <<EOF > "$release_body_file"
{
  "tag_name": "${TAG}",
  "name": "${TAG}",
  "body": "Tallinn Widgets release ${TAG}",
  "draft": false,
  "prerelease": false
}
EOF

    release_create="$(mktemp)"
    create_status="$(curl -sS -o "$release_create" -w '%{http_code}' -X POST \
      -H "Authorization: Bearer ${GITHUB_TOKEN}" \
      -H "Accept: application/vnd.github+json" \
      -H "X-GitHub-Api-Version: 2022-11-28" \
      -H "Content-Type: application/json" \
      --data-binary @"$release_body_file" \
      "$GITHUB_API/repos/${OWNER_REPO}/releases")"

    if [[ "$create_status" != "201" ]]; then
      echo "error: failed to create release ${TAG} (HTTP ${create_status})" >&2
      if [[ "$create_status" == "404" ]]; then
        echo "hint: GitHub returned 404. Usually this means either repo path is wrong or token lacks access." >&2
        echo "      Verify OWNER_REPO='${OWNER_REPO}' and that PAT has repository write permissions for releases." >&2
        echo "      For fine-grained PAT: at least 'Contents: Read & Write' on the target repo." >&2
      elif [[ "$create_status" == "422" ]]; then
        echo "hint: GitHub says repository is empty. Push at least one commit (eg, set branch)" >&2
        echo "      before creating the first release: git push <remote> <branch>." >&2
      fi
      cat "$release_create" >&2
      exit 1
    fi

    RELEASE_ID="$(json_field "$release_create" id)"
    UPLOAD_URL="$(json_field "$release_create" upload_url | sed 's/{.*$//')"
  fi

  if [[ -z "$RELEASE_ID" || -z "$UPLOAD_URL" ]]; then
    echo "error: no release id/upload url available for ${TAG}" >&2
    exit 1
  fi

  upload_asset() {
    local asset_path=$1
    local asset_name
    asset_name=$(basename "$asset_path")

    local resp
    local status
    resp="$(mktemp)"
    status="$(curl -sS -o "$resp" -w '%{http_code}' -X POST \
      -H "Authorization: Bearer ${GITHUB_TOKEN}" \
      -H "Accept: application/vnd.github+json" \
      -H "X-GitHub-Api-Version: 2022-11-28" \
      -H "Content-Type: application/octet-stream" \
      --data-binary @"$asset_path" \
      "${UPLOAD_URL}?name=${asset_name}")"

    if [[ "$status" != "201" ]]; then
      echo "warning: failed to upload ${asset_name} (HTTP ${status})" >&2
      cat "$resp" >&2
    fi
  }

  upload_asset "$ZIP_PATH"
  if [[ -f "$TAR_PATH" ]]; then
    upload_asset "$TAR_PATH"
  fi

else
  GITEA_HOST="${GITEA_HOST:-git.nlf.gg}"
  GITEA_API="${GITEA_API_URL:-https://${GITEA_HOST}/api/v1}"

  if [[ -z "${GITEA_TOKEN:-}" ]]; then
    echo "No GITEA_TOKEN set. Skipping auto release/create/upload." >&2
    echo "Attach package assets manually in Gitea release ${TAG}."
    echo "- $PROJECT_ROOT/dist/tallinn_widgets-${VERSION}.zip"
    echo "- $PROJECT_ROOT/dist/tallinn_widgets-${VERSION}.tar.gz"
    exit 0
  fi

  if [[ ! -f "$PROJECT_ROOT/dist/tallinn_widgets-${VERSION}.zip" ]]; then
    echo "error: expected release artifact not found: dist/tallinn_widgets-${VERSION}.zip" >&2
    exit 1
  fi

  release_lookup="$(mktemp)"
  lookup_status="$(curl -sS -o "$release_lookup" -w '%{http_code}' -H "Authorization: token ${GITEA_TOKEN}" "$GITEA_API/repos/${OWNER_REPO}/releases/tags/${TAG}")"

  RELEASE_ID=""
  if [[ "$lookup_status" == "200" ]]; then
    RELEASE_ID="$(json_field "$release_lookup" id)"
  else
    release_body_file="$(mktemp)"
    cat <<EOF > "$release_body_file"
{
  "tag_name": "${TAG}",
  "name": "${TAG}",
  "body": "Tallinn Widgets release ${TAG}",
  "draft": false,
  "prerelease": false
}
EOF

    release_create="$(mktemp)"
    create_status="$(curl -sS -o "$release_create" -w '%{http_code}' -X POST \
      -H "Authorization: token ${GITEA_TOKEN}" \
      -H "Content-Type: application/json" \
      --data-binary @"$release_body_file" \
      "$GITEA_API/repos/${OWNER_REPO}/releases")"

    if [[ "$create_status" != "201" ]]; then
      echo "error: failed to create release ${TAG} (HTTP ${create_status})" >&2
      cat "$release_create" >&2
      exit 1
    fi

    RELEASE_ID="$(json_field "$release_create" id)"
    if [[ -z "$RELEASE_ID" ]]; then
      echo "error: could not parse release id from create response" >&2
      exit 1
    fi
  fi

  if [[ -z "$RELEASE_ID" ]]; then
    echo "error: no release id available for ${TAG}" >&2
    exit 1
  fi

  upload_asset() {
    local asset_path=$1
    local asset_name
    asset_name=$(basename "$asset_path")

    local resp
    local status
    resp="$(mktemp)"
    status="$(curl -sS -o "$resp" -w '%{http_code}' -X POST \
      -H "Authorization: token ${GITEA_TOKEN}" \
      -H "Content-Type: application/octet-stream" \
      --data-binary @"$asset_path" \
      "$GITEA_API/repos/${OWNER_REPO}/releases/${RELEASE_ID}/assets?name=${asset_name}")"

    if [[ "$status" != "201" ]]; then
      echo "warning: failed to upload ${asset_name} (HTTP ${status})" >&2
      cat "$resp" >&2
    fi
  }

  upload_asset "$PROJECT_ROOT/dist/tallinn_widgets-${VERSION}.zip"

  if [[ -f "$PROJECT_ROOT/dist/tallinn_widgets-${VERSION}.tar.gz" ]]; then
    upload_asset "$PROJECT_ROOT/dist/tallinn_widgets-${VERSION}.tar.gz"
  fi
fi

echo "Release automation complete for ${TAG}."
