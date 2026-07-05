"""Tallinn Widgets sensor integration for Home Assistant."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict

import voluptuous as vol
from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity, DataUpdateCoordinator
from homeassistant.helpers.typing import ConfigType

from homeassistant.helpers import config_validation as cv

from .config_util import resolve_config_path
from .const import (
    CONF_CONFIG_PATH,
    CONF_ELRON_NAME,
    CONF_ELRON_SCAN_INTERVAL,
    CONF_TRANSIT_NAME,
    CONF_TRANSIT_SCAN_INTERVAL,
    DEFAULT_BUS_NAME,
    DEFAULT_CONFIG_PATH,
    DEFAULT_ELRON_NAME,
    DEFAULT_ELRON_SCAN_SECONDS,
    DEFAULT_TRAIN_NAME,
    DEFAULT_TRANSIT_NAME,
    DEFAULT_TRANSIT_SCAN_SECONDS,
    DEFAULT_TRAM_NAME,
    DOMAIN,
)
from .tallinn_widget_lib import (
    build_elron_payload,
    build_elron_station_departures,
    build_transit_payload,
    build_transit_station_departures,
    read_json_file,
)

_LOGGER = logging.getLogger(__name__)
STATION_BOARD_CONFIG = "station_board"
STATION_BOARD_WINDOW_MINUTES = "window_minutes"
STATION_BOARD_LIMIT = "limit"
STATION_BOARD_SENSOR_NAMES = {
    "bus": DEFAULT_BUS_NAME,
    "tram": DEFAULT_TRAM_NAME,
    "train": DEFAULT_TRAIN_NAME,
}
STATION_BOARD_ICONS = {
    "bus": "mdi:bus",
    "tram": "mdi:tram",
    "train": "mdi:train",
}

PLATFORM_SCHEMA = cv.PLATFORM_SCHEMA.extend(
    {
        vol.Optional(CONF_CONFIG_PATH, default=DEFAULT_CONFIG_PATH): cv.string,
        vol.Optional(CONF_TRANSIT_NAME, default=DEFAULT_TRANSIT_NAME): cv.string,
        vol.Optional(CONF_ELRON_NAME, default=DEFAULT_ELRON_NAME): cv.string,
        vol.Optional(
            CONF_TRANSIT_SCAN_INTERVAL, default=DEFAULT_TRANSIT_SCAN_SECONDS
        ): cv.positive_int,
        vol.Optional(
            CONF_ELRON_SCAN_INTERVAL, default=DEFAULT_ELRON_SCAN_SECONDS
        ): cv.positive_int,
    }
)


def _resolve_payload_error(error: str) -> Dict[str, Any]:
    return {
        "status": "error",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "errors": [error],
        "payload": {},
    }


def _config_path(configured: str) -> Path:
    return resolve_config_path(configured)


def _load_transit_payload(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return _resolve_payload_error(f"Config not found at {path}")
    try:
        conf = read_json_file(path)
    except Exception as exc:
        return _resolve_payload_error(f"Failed reading config {path}: {exc}")
    try:
        return build_transit_payload(conf)
    except Exception as exc:
        _LOGGER.debug("Failed building Tallinn transit payload", exc_info=True)
        return _resolve_payload_error(f"Failed building transit payload: {exc}")


def _load_elron_payload(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return _resolve_payload_error(f"Config not found at {path}")
    try:
        conf = read_json_file(path)
    except Exception as exc:
        return _resolve_payload_error(f"Failed reading config {path}: {exc}")
    try:
        return build_elron_payload(conf)
    except Exception as exc:
        _LOGGER.debug("Failed building Tallinn Elron payload", exc_info=True)
        return _resolve_payload_error(f"Failed building Elron payload: {exc}")


def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, parsed)


def _nonblank_config_items(config: Dict[str, Any]) -> Dict[str, Any]:
    return {
        key: value
        for key, value in config.items()
        if value is not None and str(value).strip() != ""
    }


def _default_station_board_config() -> Dict[str, Any]:
    default_config_path = Path(__file__).with_name("config.example.json")
    try:
        config = read_json_file(default_config_path)
    except Exception:
        return {}
    station_board = config.get(STATION_BOARD_CONFIG, {})
    return dict(station_board) if isinstance(station_board, dict) else {}


def _station_board_config(config: Dict[str, Any]) -> Dict[str, Any]:
    configured = config.get(STATION_BOARD_CONFIG, {})
    if not isinstance(configured, dict):
        configured = {}

    explicit = _nonblank_config_items(configured)
    merged = _default_station_board_config()
    merged.update(explicit)
    if explicit.get("elron_station") and "train_station" not in explicit:
        merged["train_station"] = explicit["elron_station"]
    return merged


def _station_board_section_error(kind: str, error: str) -> Dict[str, Any]:
    return {
        "status": "error",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "errors": [error],
        "payload": {
            "transport_type": kind,
            "station": "",
            "departures": [],
            "count": 0,
        },
    }


def _station_board_section(
    config: Dict[str, Any],
    kind: str,
    station: str,
    window_minutes: int,
    limit: int,
) -> Dict[str, Any]:
    if not station:
        return _station_board_section_error(
            kind,
            f"Missing {STATION_BOARD_CONFIG}.{kind}_station in config",
        )

    if kind in {"bus", "tram"}:
        result = build_transit_station_departures(
            config,
            station,
            window_minutes,
            limit,
            kind,
        )
    else:
        http_conf = config.get("http", {})
        result = build_elron_station_departures(
            station,
            window_minutes,
            limit,
            int(http_conf.get("timeout_seconds", 20)),
            str(http_conf.get("user_agent", "HomeAssistant Tallinn Widgets")),
        )

    payload = result.setdefault("payload", {})
    payload["transport_type"] = kind
    return result


def _load_station_board_payload(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return _resolve_payload_error(f"Config not found at {path}")
    try:
        config = read_json_file(path)
    except Exception as exc:
        return _resolve_payload_error(f"Failed reading config {path}: {exc}")

    board_config = _station_board_config(config)
    window_minutes = _positive_int(
        board_config.get(STATION_BOARD_WINDOW_MINUTES, 60),
        60,
    )
    limit = _positive_int(board_config.get(STATION_BOARD_LIMIT, 80), 80)
    stations = {
        "bus": str(board_config.get("bus_station", "") or "").strip(),
        "tram": str(board_config.get("tram_station", "") or "").strip(),
        "train": str(
            board_config.get("train_station", "")
            or board_config.get("elron_station", "")
            or ""
        ).strip(),
    }

    sections: Dict[str, Dict[str, Any]] = {}
    errors = []
    for kind, station in stations.items():
        try:
            section = _station_board_section(
                config,
                kind,
                station,
                window_minutes,
                limit,
            )
        except Exception as exc:
            _LOGGER.debug("Failed building Tallinn %s station payload", kind, exc_info=True)
            section = _station_board_section_error(
                kind,
                f"Failed building {kind} station payload: {exc}",
            )
        sections[kind] = section
        errors.extend(section.get("errors", []))

    if all(section.get("status") == "error" for section in sections.values()):
        status = "error"
    elif errors:
        status = "partial"
    else:
        status = "ok"

    return {
        "status": status,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "errors": errors,
        "payload": {"sections": sections},
    }


async def _async_add_tallinn_entities(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
) -> None:
    config_path = _config_path(config.get(CONF_CONFIG_PATH, DEFAULT_CONFIG_PATH))
    transit_interval = timedelta(
        seconds=config.get(CONF_TRANSIT_SCAN_INTERVAL, DEFAULT_TRANSIT_SCAN_SECONDS)
    )
    elron_interval = timedelta(
        seconds=config.get(CONF_ELRON_SCAN_INTERVAL, DEFAULT_ELRON_SCAN_SECONDS)
    )

    async def _async_load_transit_payload() -> Dict[str, Any]:
        return await hass.async_add_executor_job(_load_transit_payload, config_path)

    async def _async_load_elron_payload() -> Dict[str, Any]:
        return await hass.async_add_executor_job(_load_elron_payload, config_path)

    async def _async_load_station_board_payload() -> Dict[str, Any]:
        return await hass.async_add_executor_job(_load_station_board_payload, config_path)

    transit_coordinator = DataUpdateCoordinator(
        hass,
        logger=_LOGGER,
        name="Tallinn Transit Widget",
        update_interval=transit_interval,
        update_method=_async_load_transit_payload,
    )

    elron_coordinator = DataUpdateCoordinator(
        hass,
        logger=_LOGGER,
        name="Tallinn Elron Widget",
        update_interval=elron_interval,
        update_method=_async_load_elron_payload,
    )

    station_board_coordinator = DataUpdateCoordinator(
        hass,
        logger=_LOGGER,
        name="Tallinn Station Board",
        update_interval=min(transit_interval, elron_interval),
        update_method=_async_load_station_board_payload,
    )

    await transit_coordinator.async_config_entry_first_refresh()
    await elron_coordinator.async_config_entry_first_refresh()
    await station_board_coordinator.async_config_entry_first_refresh()

    async_add_entities(
        [
            _TallinnSensorEntity(
                transit_coordinator,
                config.get(CONF_TRANSIT_NAME, DEFAULT_TRANSIT_NAME),
                "transit",
            ),
            _TallinnSensorEntity(
                elron_coordinator,
                config.get(CONF_ELRON_NAME, DEFAULT_ELRON_NAME),
                "elron",
            ),
            *(
                _StationBoardSensorEntity(
                    station_board_coordinator,
                    name,
                    kind,
                )
                for kind, name in STATION_BOARD_SENSOR_NAMES.items()
            ),
        ],
        True,
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Tallinn Widgets sensors from a config entry."""
    config = dict(entry.data)
    config.update(entry.options)
    await _async_add_tallinn_entities(hass, config, async_add_entities)


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info=None,
) -> None:
    """Set up Tallinn Widgets sensors from legacy YAML."""
    await _async_add_tallinn_entities(hass, config, async_add_entities)


class _TallinnSensorEntity(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator: DataUpdateCoordinator, name: str, kind: str):
        super().__init__(coordinator)
        self._kind = kind
        self._attr_name = name
        self._attr_unique_id = f"{DOMAIN}_{kind}"

    @property
    def native_value(self) -> str | None:
        if not self.coordinator.data:
            return None
        return str(self.coordinator.data.get("updated_at", ""))

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        if not self.coordinator.data:
            return {
                "payload": {},
                "errors": ["No data yet"],
                "status": "error",
            }

        return {
            "payload": self.coordinator.data.get("payload", {}),
            "errors": self.coordinator.data.get("errors", []),
            "status": self.coordinator.data.get("status", "error"),
        }


class _StationBoardSensorEntity(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator: DataUpdateCoordinator, name: str, kind: str):
        super().__init__(coordinator)
        self._kind = kind
        self._attr_name = name
        self._attr_unique_id = f"{DOMAIN}_{kind}"
        self._attr_icon = STATION_BOARD_ICONS.get(kind)

    def _section(self) -> Dict[str, Any]:
        if not self.coordinator.data:
            return _station_board_section_error(self._kind, "No data yet")
        sections = self.coordinator.data.get("payload", {}).get("sections", {})
        section = sections.get(self._kind)
        if not isinstance(section, dict):
            errors = self.coordinator.data.get("errors", [])
            message = "; ".join(str(error) for error in errors) or "No data yet"
            return _station_board_section_error(self._kind, message)
        return section

    def _departure_label(self, row: Dict[str, Any]) -> str:
        route = row.get("line") or row.get("route") or row.get("trip") or ""
        due = row.get("due") or row.get("in_minutes") or row.get("time") or ""
        label = " ".join(str(part).strip() for part in (route, due) if part)
        return label or "next"

    @property
    def native_value(self) -> str:
        section = self._section()
        payload = section.get("payload", {})
        if section.get("status") == "error":
            return "error"
        departures = payload.get("departures", [])
        if departures and isinstance(departures[0], dict):
            return self._departure_label(departures[0])
        return "none"

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        section = self._section()
        payload = section.get("payload", {})
        departures = payload.get("departures", [])
        next_departure = departures[0] if departures and isinstance(departures[0], dict) else None

        return {
            "payload": payload,
            "errors": section.get("errors", []),
            "status": section.get("status", "error"),
            "transport_type": self._kind,
            "station": payload.get("station", ""),
            "departures": departures,
            "next_departure": next_departure,
            "updated_at": section.get("updated_at", ""),
        }
