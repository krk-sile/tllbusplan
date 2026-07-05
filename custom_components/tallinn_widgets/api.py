"""HTTP API views for Tallinn Widgets."""

from __future__ import annotations

from http import HTTPStatus
from pathlib import Path
from typing import Any

from aiohttp import web

from homeassistant.components.http import KEY_HASS, HomeAssistantView, StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .config_util import read_widget_config
from .const import CONF_CONFIG_PATH, DEFAULT_CONFIG_PATH, DOMAIN
from .tallinn_widget_lib import (
    build_elron_station_departures,
    build_elron_station_list,
    build_transit_station_departures,
    build_transit_station_list,
)

DATA_API_REGISTERED = "api_registered"
DATA_STATIC_REGISTERED = "static_registered"


def _entry_config(entry: ConfigEntry | None) -> dict[str, Any]:
    if entry is None:
        return {CONF_CONFIG_PATH: DEFAULT_CONFIG_PATH}

    config = dict(entry.data)
    config.update(entry.options)
    return config


async def _async_widget_config(hass: HomeAssistant) -> dict[str, Any]:
    entry = next(iter(hass.config_entries.async_entries(DOMAIN)), None)
    entry_data = _entry_config(entry)
    configured_path = str(entry_data.get(CONF_CONFIG_PATH, DEFAULT_CONFIG_PATH))
    return await hass.async_add_executor_job(read_widget_config, configured_path)


def _int_query(request: web.Request, name: str, default: int, maximum: int) -> int:
    try:
        value = int(request.query.get(name, default))
    except (TypeError, ValueError):
        return default
    return max(1, min(value, maximum))


def _mode_query(request: web.Request) -> str:
    mode = request.query.get("mode", "").strip().lower()
    return mode if mode in {"bus", "tram"} else ""


class TallinnTransitStationsView(HomeAssistantView):
    """Return public transit station search results."""

    url = "/api/tallinn_widgets/transit/stations"
    name = "api:tallinn_widgets:transit_stations"

    async def get(self, request: web.Request) -> web.Response:
        hass: HomeAssistant = request.app[KEY_HASS]
        query = request.query.get("q", "")
        limit = _int_query(request, "limit", 30, 100)
        mode = _mode_query(request)
        try:
            config = await _async_widget_config(hass)
            payload = await hass.async_add_executor_job(
                build_transit_station_list, config, query, limit, mode
            )
        except FileNotFoundError:
            return self.json_message("Tallinn Widgets config not found", HTTPStatus.NOT_FOUND)
        except Exception as exc:  # pylint: disable=broad-except
            return self.json_message(str(exc), HTTPStatus.INTERNAL_SERVER_ERROR)
        return self.json(payload)


class TallinnTransitDeparturesView(HomeAssistantView):
    """Return next public transit departures for a station."""

    url = "/api/tallinn_widgets/transit/departures"
    name = "api:tallinn_widgets:transit_departures"

    async def get(self, request: web.Request) -> web.Response:
        hass: HomeAssistant = request.app[KEY_HASS]
        station = request.query.get("station", "")
        window_minutes = _int_query(request, "window", 60, 180)
        limit = _int_query(request, "limit", 80, 200)
        mode = _mode_query(request)
        try:
            config = await _async_widget_config(hass)
            payload = await hass.async_add_executor_job(
                build_transit_station_departures,
                config,
                station,
                window_minutes,
                limit,
                mode,
            )
        except FileNotFoundError:
            return self.json_message("Tallinn Widgets config not found", HTTPStatus.NOT_FOUND)
        except Exception as exc:  # pylint: disable=broad-except
            return self.json_message(str(exc), HTTPStatus.INTERNAL_SERVER_ERROR)
        return self.json(payload)


class TallinnElronStationsView(HomeAssistantView):
    """Return Elron station search results."""

    url = "/api/tallinn_widgets/elron/stations"
    name = "api:tallinn_widgets:elron_stations"

    async def get(self, request: web.Request) -> web.Response:
        query = request.query.get("q", "")
        limit = _int_query(request, "limit", 50, 200)
        try:
            payload = await request.app[KEY_HASS].async_add_executor_job(
                build_elron_station_list, query, limit
            )
        except Exception as exc:  # pylint: disable=broad-except
            return self.json_message(str(exc), HTTPStatus.INTERNAL_SERVER_ERROR)
        return self.json(payload)


class TallinnElronDeparturesView(HomeAssistantView):
    """Return next Elron departures for a station."""

    url = "/api/tallinn_widgets/elron/departures"
    name = "api:tallinn_widgets:elron_departures"

    async def get(self, request: web.Request) -> web.Response:
        station = request.query.get("station", "")
        window_minutes = _int_query(request, "window", 60, 180)
        limit = _int_query(request, "limit", 80, 200)
        try:
            payload = await request.app[KEY_HASS].async_add_executor_job(
                build_elron_station_departures,
                station,
                window_minutes,
                limit,
            )
        except Exception as exc:  # pylint: disable=broad-except
            return self.json_message(str(exc), HTTPStatus.INTERNAL_SERVER_ERROR)
        return self.json(payload)


async def async_setup_api(hass: HomeAssistant) -> None:
    """Register Tallinn Widgets HTTP API and static frontend assets."""
    data = hass.data.setdefault(DOMAIN, {})
    if not data.get(DATA_API_REGISTERED):
        hass.http.register_view(TallinnTransitStationsView)
        hass.http.register_view(TallinnTransitDeparturesView)
        hass.http.register_view(TallinnElronStationsView)
        hass.http.register_view(TallinnElronDeparturesView)
        data[DATA_API_REGISTERED] = True

    static_path = Path(__file__).with_name("www")
    if static_path.exists() and not data.get(DATA_STATIC_REGISTERED):
        await hass.http.async_register_static_paths(
            [
                StaticPathConfig(
                    "/tallinn_widgets_static",
                    str(static_path),
                    False,
                )
            ]
        )
        data[DATA_STATIC_REGISTERED] = True
