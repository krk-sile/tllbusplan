# Tallinn Widgets for Home Assistant

Tallinn Widgets is a Home Assistant custom integration for two dashboard
widgets:

1. Tallinn public transit departures for configured favorite stops/routes.
2. Elron trip departure tables for configured train trip IDs.

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

Edit:

- `transit.favorites` for Tallinn public transport favorites.
- `trains.trips` for Elron trip IDs.

## Dashboard Cards

This release also includes Lovelace Markdown card snippets:

- `tallinn_widgets/ha/lovelace/tallinn_transit_card.yaml`
- `tallinn_widgets/ha/lovelace/elron_train_card.yaml`

Add them as manual cards in the Home Assistant dashboard UI. If Home Assistant
assigns different entity IDs, adjust the `sensor.tallinn_transit_board` and
`sensor.tallinn_elron_trips` references in those card snippets.
