"""Tallinn Widgets sensor integration for Home Assistant."""

from __future__ import annotations

import logging
from datetime import timedelta
from pathlib import Path
from typing import Any, Dict

import voluptuous as vol
from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity, DataUpdateCoordinator
from homeassistant.helpers.typing import ConfigType
from homeassistant.util import dt as dt_util

from homeassistant.helpers import config_validation as cv

from .tallinn_widget_lib import build_elron_payload, build_transit_payload, read_json_file

_LOGGER = logging.getLogger(__name__)

CONF_CONFIG_PATH = "config_path"
CONF_ELRON_NAME = "elron_sensor_name"
CONF_TRANSIT_NAME = "transit_sensor_name"
CONF_ELRON_SCAN_INTERVAL = "elron_scan_interval"
CONF_TRANSIT_SCAN_INTERVAL = "transit_scan_interval"

DEFAULT_CONFIG_PATH = "/config/tallinn_widgets/config.json"
DEFAULT_TRANSIT_NAME = "Tallinn Transit Board"
DEFAULT_ELRON_NAME = "Tallinn Elron Trips"
DEFAULT_TRANSIT_SCAN_SECONDS = 45
DEFAULT_ELRON_SCAN_SECONDS = 60

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
        "updated_at": dt_util.utcnow().isoformat(),
        "errors": [error],
        "payload": {},
    }


def _config_path(configured: str) -> Path:
    explicit = Path(configured).expanduser()
    if explicit.exists():
        return explicit

    candidates = [
        Path("/config/tallinn_widgets/config.json"),
        Path("/config/tallinn_widgets/config.example.json"),
        explicit,
    ]

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return explicit


def _load_transit_payload(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return _resolve_payload_error(f"Config not found at {path}")
    try:
        conf = read_json_file(path)
    except Exception as exc:
        return _resolve_payload_error(f"Failed reading config {path}: {exc}")
    return build_transit_payload(conf)


def _load_elron_payload(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return _resolve_payload_error(f"Config not found at {path}")
    try:
        conf = read_json_file(path)
    except Exception as exc:
        return _resolve_payload_error(f"Failed reading config {path}: {exc}")
    return build_elron_payload(conf)


async def async_setup_platform(hass, config: ConfigType, async_add_entities: AddEntitiesCallback, discovery_info=None):
    config_path = _config_path(config.get(CONF_CONFIG_PATH, DEFAULT_CONFIG_PATH))
    transit_interval = timedelta(seconds=config.get(CONF_TRANSIT_SCAN_INTERVAL, DEFAULT_TRANSIT_SCAN_SECONDS))
    elron_interval = timedelta(seconds=config.get(CONF_ELRON_SCAN_INTERVAL, DEFAULT_ELRON_SCAN_SECONDS))

    transit_coordinator = DataUpdateCoordinator(
        hass,
        logger=_LOGGER,
        name="Tallinn Transit Widget",
        update_interval=transit_interval,
        update_method=lambda: hass.async_add_executor_job(_load_transit_payload, config_path),
    )

    elron_coordinator = DataUpdateCoordinator(
        hass,
        logger=_LOGGER,
        name="Tallinn Elron Widget",
        update_interval=elron_interval,
        update_method=lambda: hass.async_add_executor_job(_load_elron_payload, config_path),
    )

    await transit_coordinator.async_config_entry_first_refresh()
    await elron_coordinator.async_config_entry_first_refresh()

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
        ],
        True,
    )


class _TallinnSensorEntity(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator: DataUpdateCoordinator, name: str, kind: str):
        super().__init__(coordinator)
        self._kind = kind
        self._attr_name = name
        self._attr_unique_id = f"tallinn_widgets_{kind}"

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
