#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: ./scripts/package_tallinn_widgets.sh [VERSION]

Creates: dist/tallinn_widgets-<version>.tar.gz

If VERSION is omitted, it uses the latest git tag (if present),
or a date+git-short-fallback version.
EOF
}

if [[ "${1-}" == "-h" || "${1-}" == "--help" ]]; then
  usage
  exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

if [[ $# -gt 1 ]]; then
  echo "error: too many arguments" >&2
  usage >&2
  exit 1
fi

VERSION="${1-}"
if [[ -z "$VERSION" ]]; then
  VERSION="$(git -C "$PROJECT_ROOT" describe --tags --abbrev=0 2>/dev/null || true)"
  if [[ -z "$VERSION" ]]; then
    if [[ -d "$PROJECT_ROOT/.git" ]]; then
      COMMIT="$(git -C "$PROJECT_ROOT" rev-parse --short HEAD 2>/dev/null || echo unknown)"
    else
      COMMIT="local"
    fi
    VERSION="0.1.0-$(date -u +%Y%m%d)-${COMMIT}"
  fi
fi
VERSION="${VERSION#v}"

DIST_DIR="$PROJECT_ROOT/dist"
mkdir -p "$DIST_DIR"

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

PACKAGE_NAME="tallinn_widgets-${VERSION}"
PACKAGE_DIR="$TMP_DIR/$PACKAGE_NAME"
mkdir -p "$PACKAGE_DIR"

cp -R "$PROJECT_ROOT/tallinn_widgets" "$PACKAGE_DIR/"
cp "$PROJECT_ROOT/scripts/install_tallinn_widgets.sh" "$PACKAGE_DIR/"
cp "$PROJECT_ROOT/scripts/package_tallinn_widgets.sh" "$PACKAGE_DIR/"
cp "$PROJECT_ROOT/README.md" "$PACKAGE_DIR/"
if [[ -f "$PROJECT_ROOT/hacs.json" ]]; then
  cp "$PROJECT_ROOT/hacs.json" "$PACKAGE_DIR/"
fi
if [[ -d "$PROJECT_ROOT/custom_components" ]]; then
  cp -R "$PROJECT_ROOT/custom_components" "$PACKAGE_DIR/"
fi

cat > "$PACKAGE_DIR/release-notes.md" <<EOF
Tallinn Widgets package

Version: $VERSION
Built at: $(date -u +'%Y-%m-%dT%H:%M:%SZ')
Git: $(git -C "$PROJECT_ROOT" rev-parse --short HEAD 2>/dev/null || echo unavailable)
Files:
- install_tallinn_widgets.sh
- tallinn_widgets/scripts/*.py
- tallinn_widgets/config.example.json
- custom_components/tallinn_widgets
- hacs.json
- tallinn_widgets/ha/lovelace/tallinn_transit_card.yaml
- tallinn_widgets/ha/lovelace/elron_train_card.yaml
- tallinn_widgets/ha/packages/tallinn_widgets.yaml
EOF

ARCHIVE_TAR="$DIST_DIR/${PACKAGE_NAME}.tar.gz"
ARCHIVE_ZIP="$DIST_DIR/${PACKAGE_NAME}.zip"
tar -C "$TMP_DIR" -czf "$ARCHIVE_TAR" "$PACKAGE_NAME"
if command -v zip >/dev/null 2>&1; then
  (cd "$TMP_DIR" && zip -qr "$ARCHIVE_ZIP" "$PACKAGE_NAME")
else
  echo "warning: zip not found, skipping zip archive"
fi

if command -v sha256sum >/dev/null 2>&1; then
  sha256sum "$ARCHIVE_TAR" | awk '{print $1"  "$2}' > "$ARCHIVE_TAR.sha256"
  if [[ -f "$ARCHIVE_ZIP" ]]; then
    sha256sum "$ARCHIVE_ZIP" | awk '{print $1"  "$2}' > "$ARCHIVE_ZIP.sha256"
  fi
else
  shasum -a 256 "$ARCHIVE_TAR" | awk '{print $1"  "$2}' > "$ARCHIVE_TAR.sha256"
  if [[ -f "$ARCHIVE_ZIP" ]]; then
    shasum -a 256 "$ARCHIVE_ZIP" | awk '{print $1"  "$2}' > "$ARCHIVE_ZIP.sha256"
  fi
fi

if [[ -f "$ARCHIVE_ZIP" ]]; then
  echo "Built package: $ARCHIVE_TAR"
  echo "Built package: $ARCHIVE_ZIP"
  echo "Checksum: ${ARCHIVE_TAR}.sha256"
  echo "Checksum: ${ARCHIVE_ZIP}.sha256"
else
  echo "Built package: $ARCHIVE_TAR"
  echo "Checksum: ${ARCHIVE_TAR}.sha256"
fi
echo "Version: $VERSION"
