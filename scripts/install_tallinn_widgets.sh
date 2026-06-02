#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: ./scripts/install_tallinn_widgets.sh [OPTIONS] [HA_CONFIG_DIR]

Options:
  --help            Show this help message
  --force-config    Overwrite existing config.json with example values

Positional:
  HA_CONFIG_DIR     Home Assistant config dir (default: /config)
EOF
}

HA_CONFIG_DIR="/config"
FORCE_CONFIG=0

if [[ $# -gt 0 ]]; then
  case "$1" in
    --help|-h)
      usage
      exit 0
      ;;
    --force-config)
      FORCE_CONFIG=1
      shift
      ;;
  esac
fi

if [[ $# -gt 1 ]]; then
  echo "error: too many arguments" >&2
  usage >&2
  exit 1
fi

if [[ $# -eq 1 ]]; then
  HA_CONFIG_DIR="$1"
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SOURCE_ROOT="$PROJECT_ROOT/tallinn_widgets"
TARGET_ROOT="${HA_CONFIG_DIR%/}/tallinn_widgets"

if [[ ! -d "$HA_CONFIG_DIR" ]]; then
  echo "error: Home Assistant config dir does not exist: $HA_CONFIG_DIR" >&2
  exit 1
fi

mkdir -p "$TARGET_ROOT/scripts" \
         "$TARGET_ROOT/ha/packages" \
         "$TARGET_ROOT/ha/lovelace"

cp "$SOURCE_ROOT/config.example.json" "$TARGET_ROOT/config.example.json"
cp "$SOURCE_ROOT/ha/packages/tallinn_widgets.yaml" "$TARGET_ROOT/ha/packages/tallinn_widgets.yaml"
cp "$SOURCE_ROOT/ha/lovelace/tallinn_transit_card.yaml" "$TARGET_ROOT/ha/lovelace/tallinn_transit_card.yaml"
cp "$SOURCE_ROOT/ha/lovelace/elron_train_card.yaml" "$TARGET_ROOT/ha/lovelace/elron_train_card.yaml"
cp "$SOURCE_ROOT/scripts/tallinn_transit_widget.py" "$TARGET_ROOT/scripts/tallinn_transit_widget.py"
cp "$SOURCE_ROOT/scripts/tallinn_elron_widget.py" "$TARGET_ROOT/scripts/tallinn_elron_widget.py"
cp "$SOURCE_ROOT/scripts/tallinn_widget_lib.py" "$TARGET_ROOT/scripts/tallinn_widget_lib.py"
chmod +x "$TARGET_ROOT/scripts/tallinn_transit_widget.py" "$TARGET_ROOT/scripts/tallinn_elron_widget.py"

if [[ ! -f "$TARGET_ROOT/config.json" || $FORCE_CONFIG -eq 1 ]]; then
  cp "$SOURCE_ROOT/config.example.json" "$TARGET_ROOT/config.json"
  if [[ $FORCE_CONFIG -eq 1 ]]; then
    echo "Overwrote config.json with example values"
  else
    echo "Created config.json from example values"
  fi
fi

cat <<EOF
Installed widget package to: $TARGET_ROOT

Next steps:
1) Edit $TARGET_ROOT/config.json with your routes/trips.
2) Ensure Home Assistant packages include:

homeassistant:
  packages: !include_dir_named tallinn_widgets/ha/packages

3) Add the Lovelace cards from:
   $TARGET_ROOT/ha/lovelace/tallinn_transit_card.yaml
   $TARGET_ROOT/ha/lovelace/elron_train_card.yaml

You can rerun this installer to update scripts/config files after repo changes.
EOF
