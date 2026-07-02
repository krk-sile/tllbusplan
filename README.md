# Tallinn Widgets for Home Assistant

Tallinn Widgets is a Home Assistant custom integration for dashboard transit
widgets:

1. Tallinn public transit departures for configured favorite stops/routes.
2. Elron trip departure tables for configured train trip IDs.
3. A selectable station board for Tallinn buses/trams and Elron trains.

This GitHub repository is the curated public HACS distribution snapshot. The
working source repository lives in Gitea; only release-ready files are published
here.

## Install with HACS

1. In HACS, add a custom repository:
   - URL: `https://github.com/krk-sile/tllbusplan`
   - Type: `Integration`
2. Install **Tallinn Widgets** and restart Home Assistant.
3. Go to **Settings -> Devices & services -> Add integration** and add
   **Tallinn Widgets**.
4. Use `/config/tallinn_widgets/config.json` as the config path unless you keep
   the config elsewhere.

## Config

Create `/config/tallinn_widgets/config.json` from:

```text
tallinn_widgets/config.example.json
```

If the file is not present yet and the integration is still using the default
config path, Tallinn Widgets falls back to its bundled example config.

Edit:

- `transit.favorites` for Tallinn public transport favorites.
- `trains.trips` for Elron trip IDs.

## Dashboard Cards

This release includes Lovelace card snippets:

- `tallinn_widgets/ha/lovelace/station_board_card.yaml`
- `tallinn_widgets/ha/lovelace/tallinn_transit_card.yaml`
- `tallinn_widgets/ha/lovelace/elron_train_card.yaml`

For the station board, add this Lovelace resource as a JavaScript module:

```text
/tallinn_widgets_static/tallinn-widgets-card.js
```

Then add `station_board_card.yaml` as a manual card. Station defaults are saved
only in local browser storage.

The other two snippets are Markdown cards backed by the integration sensors. If
Home Assistant assigns different entity IDs, adjust the
`sensor.tallinn_transit_board` and `sensor.tallinn_elron_trips` references in
those card snippets.
