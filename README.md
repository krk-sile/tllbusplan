# Tallinn Transit + Elron Widgets for Home Assistant

This is a lightweight RnD implementation for two dashboard widgets:

1. Public transit departures (Tallinn) with GTFS-based ID resolution once per day.
2. Elron trip departure table from `elron.ee/live-map/trip/{trip_id}`.

It intentionally reuses the public feed ideas from the existing `zaifkhan/tallinn_transport`
project (API endpoint + data style), but the implementation is a new homegrown script+template flow.

## Files

- `tallinn_widgets/scripts/tallinn_widget_lib.py`  
  Shared parser/cache/formatter logic.
- `tallinn_widgets/scripts/tallinn_transit_widget.py`  
  CLI for public-transit table output.
- `tallinn_widgets/scripts/tallinn_elron_widget.py`  
  CLI for Elron trips.
- `tallinn_widgets/config.example.json`  
  Editable config template (copy to `config.json`).
- `tallinn_widgets/ha/packages/tallinn_widgets.yaml`  
  Home Assistant command_line sensors.
- `tallinn_widgets/ha/lovelace/tallinn_transit_card.yaml`
- `tallinn_widgets/ha/lovelace/elron_train_card.yaml`
- `custom_components/tallinn_widgets`
- `hacs.json`

## HACS install (recommended)

1. Add a custom integration repository in HACS:
   - URL: `https://github.com/siled/busplan`
   - Type: `Integration`
2. Install/Update through HACS UI.
3. Add to `configuration.yaml`:

```yaml
sensor:
  - platform: tallinn_widgets
    config_path: /config/tallinn_widgets/config.json
    transit_sensor_name: Tallinn Transit Board
    elron_sensor_name: Tallinn Elron Trips
    transit_scan_interval: 45
    elron_scan_interval: 60
```

4. Keep `/config/tallinn_widgets/config.json` updated with your stops/trips.

   You can either keep using the install script from this repo:

```bash
./scripts/install_tallinn_widgets.sh /config
```

   ...or create the folder/file manually.

5. Add the dashboard cards:

- `tallinn_widgets/ha/lovelace/tallinn_transit_card.yaml`
- `tallinn_widgets/ha/lovelace/elron_train_card.yaml`

HACS will handle updates for the integration files; config remains local.

## Setup

### Fast package install

1. From repository root, run:

```bash
./scripts/install_tallinn_widgets.sh /config
```

2. Edit `/config/tallinn_widgets/config.json`:
   - Add up to 5 transit favorites in `transit.favorites`.
   - Add up to 5 train trip IDs in `trains.trips`.

3. In Home Assistant, include the package file:

```bash
homeassistant:
  packages: !include_dir_named tallinn_widgets/ha/packages
```

You can rerun `install_tallinn_widgets.sh` anytime to update deployed scripts and HA YAML without touching your config.

### Compatibility (manual install)

1. Copy `tallinn_widgets/config.example.json` to `/config/tallinn_widgets/config.json`.
2. Edit the config:
   - Add up to 5 transit favorites in `transit.favorites`.
   - Add up to 5 train trip IDs in `trains.trips`.
3. Make scripts executable (optional, but convenient):

```bash
chmod +x /config/tallinn_widgets/scripts/*.py
```

4. In Home Assistant, include the package file:

```yaml
homeassistant:
  packages: !include_dir_named ha/packages
```

If you already use a package system, include:

```yaml
!include tallinn_widgets/ha/packages/tallinn_widgets.yaml
```

5. Add the cards to a dashboard:

- `tallinn_widgets/ha/lovelace/tallinn_transit_card.yaml`
- `tallinn_widgets/ha/lovelace/elron_train_card.yaml`

## How GTFS-to-ID resolution works

- GTFS is fetched from `gtfs_url` at most once every 24 hours and cached in `gtfs_cache_path`.
- Each favorite entry in config defines:
  - `stop_name`
  - `route_short_name`
  - `headsign` (direction)
- Resolver logic:
  - maps route short name -> route ids
  - maps route ids -> trips
  - uses trip headsign and stop names to find best `stop_id`
- If GTFS fails to produce a match, the entry is reported in `errors`.

## Polling

- Transit widget command-line sensor runs every **45 seconds** (configurable in package file).
- Elron widget runs every **60 seconds**.

Both read the same config and output JSON in this schema:

```json
{
  "status": "ok|partial|error",
  "updated_at": "timestamp",
  "payload": { ... },
  "errors": []
}
```

## Notes

- `tallinn.ee` / `elron.ee` responses are live and sometimes vary in shape.
- This implementation uses robust field heuristics for departure rows and returns best-effort rows if the schema shifts.
- You can hardcode `stop_id` for an entry if GTFS matching is not stable for a specific stop.

## Distribution package + Gitea/GitHub publish

Build a versioned release archive:

```bash
./scripts/package_tallinn_widgets.sh 1.2.3
```

This creates:

- `dist/tallinn_widgets-1.2.3.tar.gz`
- `dist/tallinn_widgets-1.2.3.tar.gz.sha256`

Publish changes + tag to GitHub/Gitea:

```bash
git add .
git commit -m "..."
./scripts/publish_to_github.sh krk-sile/tllbusplan v1.2.3
```

The GitHub publish script:

- builds the package for that tag,
- ensures remote `origin` points to `github.com`,
- pushes current branch and tag.

Attach `dist/tallinn_widgets-1.2.3.tar.gz` to a release in GitHub UI or API afterwards.

## One-command release

```bash
./scripts/release.sh --backend github v1.2.7 krk-sile/tllbusplan

## Remote setup checks

Keep both remotes explicit so the scripts don't guess wrong targets:

```bash
git remote remove origin  # optional, if your origin points to the wrong host
git remote remove github  # optional
git remote add origin git@github.com:YOUR_GITHUB_USER/YOUR_REPO.git
git remote add github git@github.com:YOUR_GITHUB_USER/YOUR_REPO.git
git remote add gitea git@git.nlf.gg:YOUR_GITEA_USER/YOUR_REPO.git
git remote -v
```

Then run release against the intended remote:

```bash
./scripts/release.sh --backend github --remote github --allow-dirty 1.2.7 krk-sile/tllbusplan
```
```

What it does:

- Updates `custom_components/tallinn_widgets/manifest.json` version from the release tag.
- Builds and checksums both `.zip` and `.tar.gz` release artifacts.
- Pushes commit + tag to `origin` (GitHub by default, or Gitea with `--backend gitea`).
- Creates/updates release for the tag.
- Uploads both assets to the release automatically when `GITEA_TOKEN` is set.

Optional env vars:

- `GITEA_TOKEN` (required for auto release creation and upload)
- `GITEA_HOST` (default `git.nlf.gg`)
- `GITEA_OWNER_REPO` (default `siled/busplan`)
- `GITHUB_OWNER_REPO` (default `siled/busplan`)
- `GITHUB_TOKEN`/`GH_TOKEN`/`GH_PAT`/`GITHUB_PAT`
- `PUBLISH_BACKEND` (`github` or `gitea`)
- `GITHUB_REMOTE` (default `github`) / `GITEA_REMOTE` (default `origin`)
- `PUBLISH_REMOTE` (fallback for both)
- `--remote` (override remote on command line)

You can skip nonessential steps with:

```bash
./scripts/release.sh --skip-publish --no-release-assets v1.2.5
```
