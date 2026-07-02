"""Shared helpers for Tallinn transit + Elron Home Assistant widgets."""

from __future__ import annotations

import csv
import io
import json
import logging
import re
import unicodedata
import urllib.parse
import urllib.request
import zipfile
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

GTFS_TTL_SECONDS = 60 * 60 * 24
STOP_API = "https://transport.tallinn.ee/siri-stop-departures.php?stopid={}"
ELRON_STOPS_URL = "https://elron.ee/stops_data.json"
ELRON_STOP_URL = "https://elron.ee/live-map/stop/{}"
PUBLIC_TRANSIT_ROUTE_TYPES = {"0": "tram", "3": "bus"}
TRANSIT_TIME_KEYS = (
    "departure_time",
    "estimated_time",
    "estimatedDeparture",
    "realtimeArrival",
    "realtimeDeparture",
    "arrival_time",
    "time",
    "departure",
    "time_iso",
    "timestamp",
    "planned_time",
    "plaaniline_aeg",
    "tegelik_aeg",
)
TRANSIT_ROUTE_KEYS = (
    "route",
    "route_short_name",
    "routeName",
    "route_number",
    "line",
    "line_name",
)
TRANSIT_DEST_KEYS = (
    "headsign",
    "destination",
    "destination_name",
    "target",
    "name",
)

ELRON_TRIP_URL = "https://elron.ee/live-map/trip/{}"

LOG = logging.getLogger(__name__)


def normalize_text(value: Any) -> str:
    """Normalize text for fuzzy matching and equality checks."""
    if value is None:
        return ""
    text = str(value)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = text.lower().strip()
    text = re.sub(r"\s+", " ", text)
    return text


def read_json_file(path: Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


def write_json_file(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)
    tmp.replace(path)


def http_get(url: str, timeout: int, user_agent: str) -> bytes:
    req = urllib.request.Request(
        url, headers={"User-Agent": user_agent, "Accept": "application/json,text/plain,*/*"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def http_get_json(url: str, timeout: int, user_agent: str) -> Any:
    return json.loads(http_get(url, timeout, user_agent).decode("utf-8", errors="ignore"))


def http_get_text(url: str, timeout: int, user_agent: str) -> str:
    return http_get(url, timeout, user_agent).decode("utf-8", errors="ignore")


def first_matching_value(record: Dict[str, Any], keys: tuple[str, ...]) -> Optional[Any]:
    for key in keys:
        if key in record and record[key] not in (None, "", []):
            return record[key]
    return None


def parse_time_to_datetime(value: Any, fallback: Optional[datetime] = None) -> Optional[datetime]:
    """Try to parse times from a few common Tallinn feed formats."""
    if value is None or value == "":
        return fallback

    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc).astimezone()
        except Exception:
            return fallback

    text = str(value).strip()
    if not text:
        return fallback

    # "YYYY-MM-DD HH:MM", "2026-06-02T12:03:04+00:00", "12:03:04", etc.
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%H:%M:%S", "%H:%M"):
        try:
            if "%Y" in fmt:
                dt = datetime.strptime(text, fmt)
            else:
                dt = datetime.strptime(text, fmt).replace(
                    year=datetime.now().year,
                    month=datetime.now().month,
                    day=datetime.now().day,
                )
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc).astimezone()
            return dt
        except Exception:
            pass

    # HHMM or just minutes-to-leave
    if re.fullmatch(r"\d{4}", text):
        try:
            now = datetime.now().astimezone()
            hour = int(text[:2])
            minute = int(text[2:])
            dt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if dt < now - timedelta(hours=1):
                dt += timedelta(days=1)
            return dt
        except Exception:
            return fallback

    return fallback


def minutes_until(target: datetime, now: datetime) -> int:
    return max(0, int((target - now).total_seconds() // 60))


def parse_int(value: Any) -> Optional[int]:
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None


def seconds_since_midnight_to_datetime(value: Any, now: datetime) -> Optional[datetime]:
    seconds = parse_int(value)
    if seconds is None or seconds < 0:
        return None

    local_now = now.astimezone()
    midnight = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    departure = midnight + timedelta(seconds=seconds)
    if departure < local_now - timedelta(hours=1):
        departure += timedelta(days=1)
    return departure


def seconds_since_midnight_to_text(value: Any) -> str:
    seconds = parse_int(value)
    if seconds is None or seconds < 0:
        return str(value) if value is not None else ""

    seconds %= 24 * 60 * 60
    hour = seconds // 3600
    minute = (seconds % 3600) // 60
    return f"{hour:02d}:{minute:02d}"


def parse_tallinn_stop_text(payload: str, now: datetime) -> List[Dict[str, Any]]:
    """Parse transport.tallinn.ee text/plain stop-board rows."""

    rows: List[Dict[str, Any]] = []
    text = payload.lstrip("\ufeff").strip()
    if not text:
        return rows

    reader = csv.reader(io.StringIO(text))
    for record in reader:
        cells = [cell.strip() for cell in record]
        if not cells:
            continue

        row_type = cells[0].lower()
        if row_type in {"transport", "stop"}:
            continue
        if len(cells) < 5:
            continue

        departure = seconds_since_midnight_to_datetime(cells[2], now)
        seconds_until = parse_int(cells[5]) if len(cells) > 5 else None
        in_minutes = None
        if seconds_until is not None:
            in_minutes = max(0, seconds_until // 60)
        elif departure is not None:
            in_minutes = minutes_until(departure, now)

        rows.append(
            {
                "route": cells[1],
                "headsign": cells[4],
                "raw_time": seconds_since_midnight_to_text(cells[2]),
                "departure_at": departure.isoformat() if departure else "",
                "in_minutes": in_minutes,
                "source": {
                    "transport": cells[0],
                    "route": cells[1],
                    "expected_seconds": cells[2],
                    "scheduled_seconds": cells[3],
                    "destination": cells[4],
                    "seconds_until": cells[5] if len(cells) > 5 else "",
                    "raw": cells,
                },
            }
        )

    rows.sort(key=lambda r: r.get("departure_at", ""))
    return rows


def flatten_departure_lists(payload: Any) -> List[List[Dict[str, Any]]]:
    """Find list-like objects that look like departure lists."""

    matches: List[List[Dict[str, Any]]] = []
    seen: set[int] = set()

    def looks_like(row: Dict[str, Any]) -> bool:
        route = first_matching_value(row, TRANSIT_ROUTE_KEYS)
        headsign = first_matching_value(row, TRANSIT_DEST_KEYS)
        tm = first_matching_value(row, TRANSIT_TIME_KEYS)
        return route is not None or headsign is not None or tm is not None

    def walk(node: Any) -> None:
        if isinstance(node, list):
            if node:
                if isinstance(node[0], dict):
                    if any(looks_like(item) for item in node if isinstance(item, dict)):
                        key = id(node)
                        if key not in seen:
                            seen.add(key)
                            matches.append(node)  # type: ignore[arg-type]
            for item in node:
                walk(item)
        elif isinstance(node, dict):
            for value in node.values():
                walk(value)

    walk(payload)
    return matches


def parse_departure_rows(payload: Any, now: datetime) -> List[Dict[str, Any]]:
    """Parse any stop-board payload into standard row objects."""
    if isinstance(payload, str):
        stripped = payload.strip()
        if not stripped:
            return []
        if stripped[0] in "[{":
            try:
                return parse_departure_rows(json.loads(stripped), now)
            except Exception:
                pass
        return parse_tallinn_stop_text(stripped, now)

    rows: List[Dict[str, Any]] = []
    candidates = flatten_departure_lists(payload)
    if not candidates:
        if isinstance(payload, list):
            candidates = [payload] if payload else []
        elif isinstance(payload, dict):
            row_like = []
            # Handle plain object payloads with top-level rows.
            for value in payload.values():
                if isinstance(value, list) and value and isinstance(value[0], dict):
                    row_like.append(value)
            if row_like:
                candidates = row_like

    for lst in candidates:
        for raw in lst:
            if not isinstance(raw, dict):
                continue
            route = first_matching_value(raw, TRANSIT_ROUTE_KEYS)
            headsign = first_matching_value(raw, TRANSIT_DEST_KEYS)
            tm_raw = first_matching_value(raw, TRANSIT_TIME_KEYS)
            dt = parse_time_to_datetime(
                tm_raw, fallback=now + timedelta(hours=24)
            )
            row = {
                "route": str(route).strip() if route is not None else "",
                "headsign": str(headsign).strip() if headsign is not None else "",
                "raw_time": str(tm_raw) if tm_raw is not None else "",
                "departure_at": dt.isoformat() if dt else "",
                "in_minutes": None if dt is None else minutes_until(dt, now),
                "source": raw,
            }
            rows.append(row)
    rows.sort(key=lambda r: r.get("departure_at", ""))
    return rows


def filter_rows_for_favorite(rows: List[Dict[str, Any]], favorite: Dict[str, Any]) -> List[Dict[str, Any]]:
    route_filter = normalize_text(favorite.get("route_short_name"))
    headsign_filter = normalize_text(favorite.get("headsign"))
    filtered = []
    for row in rows:
        row_route = normalize_text(row.get("route", ""))
        row_headsign = normalize_text(row.get("headsign", ""))
        if route_filter and row_route and row_filter_match(route_filter, row_route):
            pass
        elif route_filter and row_route and not row_filter_match(route_filter, row_route):
            continue
        elif route_filter and not row_route:
            # If row route missing, keep as a best-effort item.
            pass
        if headsign_filter and row_headsign and headsign_filter not in row_headsign:
            continue
        filtered.append(row)
    return filtered


def row_filter_match(target: str, candidate: str) -> bool:
    if not target or not candidate:
        return False
    if candidate == target:
        return True
    if target in candidate:
        return True
    return False


def stop_name_match(target: str, candidate: str) -> bool:
    if not target or not candidate:
        return False
    if target == candidate:
        return True
    if target in candidate:
        return True
    return False


def parse_csv(rows_text: str) -> List[Dict[str, str]]:
    sample = rows_text[:2000]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=";,")
    except Exception:
        dialect = csv.excel
        dialect.delimiter = ";"
    return list(csv.DictReader(io.StringIO(rows_text), dialect=dialect))


@dataclass
class GtfsCache:
    route_short_to_ids: Dict[str, List[str]]
    route_id_to_short: Dict[str, str]
    trips_by_route: Dict[str, List[str]]
    trip_headsign: Dict[str, str]
    trip_stops: Dict[str, List[str]]
    stop_id_to_name: Dict[str, str]
    stop_id_to_code: Dict[str, str]
    stop_id_to_norm_name: Dict[str, str]
    updated_at: float
    route_id_to_type: Dict[str, str] = field(default_factory=dict)
    trip_departure_times: Dict[str, List[str]] = field(default_factory=dict)
    trip_service_id: Dict[str, str] = field(default_factory=dict)
    service_calendar: Dict[str, Dict[str, str]] = field(default_factory=dict)
    service_exceptions_by_date: Dict[str, Dict[str, int]] = field(default_factory=dict)


def build_gtfs_cache(gtfs_bytes: bytes) -> GtfsCache:
    with zipfile.ZipFile(io.BytesIO(gtfs_bytes)) as zf:
        routes_rows = parse_csv(zf.read("routes.txt").decode("utf-8", errors="ignore"))
        trips_rows = parse_csv(zf.read("trips.txt").decode("utf-8", errors="ignore"))
        stop_times_rows = parse_csv(
            zf.read("stop_times.txt").decode("utf-8", errors="ignore")
        )
        stops_rows = parse_csv(zf.read("stops.txt").decode("utf-8", errors="ignore"))
        calendar_rows = (
            parse_csv(zf.read("calendar.txt").decode("utf-8", errors="ignore"))
            if "calendar.txt" in zf.namelist()
            else []
        )
        calendar_dates_rows = (
            parse_csv(zf.read("calendar_dates.txt").decode("utf-8", errors="ignore"))
            if "calendar_dates.txt" in zf.namelist()
            else []
        )

    route_short_to_ids: Dict[str, List[str]] = defaultdict(list)
    route_id_to_short: Dict[str, str] = {}
    route_id_to_type: Dict[str, str] = {}
    for row in routes_rows:
        route_id = str(row.get("route_id", "")).strip()
        route_short = str(row.get("route_short_name", "")).strip()
        if route_id:
            route_id_to_short[route_id] = route_short
            route_id_to_type[route_id] = str(row.get("route_type", "")).strip()
            if route_short:
                route_short_to_ids[normalize_text(route_short)].append(route_id)

    trips_by_route: Dict[str, List[str]] = defaultdict(list)
    trip_headsign: Dict[str, str] = {}
    trip_service_id: Dict[str, str] = {}
    for row in trips_rows:
        trip_id = str(row.get("trip_id", "")).strip()
        route_id = str(row.get("route_id", "")).strip()
        headsign = str(row.get("trip_headsign", "")).strip()
        if trip_id and route_id:
            trips_by_route[route_id].append(trip_id)
            service_id = str(row.get("service_id", "")).strip()
            if service_id:
                trip_service_id[trip_id] = service_id
            if headsign:
                trip_headsign[trip_id] = headsign

    trip_stops: Dict[str, List[str]] = defaultdict(list)
    trip_departure_times: Dict[str, List[str]] = defaultdict(list)
    for row in stop_times_rows:
        trip_id = str(row.get("trip_id", "")).strip()
        stop_id = str(row.get("stop_id", "")).strip()
        if trip_id and stop_id:
            trip_stops[trip_id].append(stop_id)
            departure_time = str(
                row.get("departure_time", "") or row.get("arrival_time", "")
            ).strip()
            trip_departure_times[trip_id].append(departure_time)

    stop_id_to_name: Dict[str, str] = {}
    stop_id_to_code: Dict[str, str] = {}
    stop_id_to_norm_name: Dict[str, str] = {}
    for row in stops_rows:
        stop_id = str(row.get("stop_id", "")).strip()
        stop_name = str(row.get("stop_name", "")).strip()
        stop_code = str(row.get("stop_code", "")).strip()
        if stop_id:
            stop_id_to_name[stop_id] = stop_name
            stop_id_to_code[stop_id] = stop_code
            stop_id_to_norm_name[stop_id] = normalize_text(stop_name)

    weekday_keys = (
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
    )
    service_calendar: Dict[str, Dict[str, str]] = {}
    for row in calendar_rows:
        service_id = str(row.get("service_id", "")).strip()
        if not service_id:
            continue
        service_calendar[service_id] = {
            "start_date": str(row.get("start_date", "")).strip(),
            "end_date": str(row.get("end_date", "")).strip(),
            **{key: str(row.get(key, "")).strip() for key in weekday_keys},
        }

    service_exceptions_by_date: Dict[str, Dict[str, int]] = defaultdict(dict)
    for row in calendar_dates_rows:
        service_id = str(row.get("service_id", "")).strip()
        service_date = str(row.get("date", "")).strip()
        exception_type = parse_int(row.get("exception_type"))
        if service_id and service_date and exception_type is not None:
            service_exceptions_by_date[service_date][service_id] = exception_type

    return GtfsCache(
        route_short_to_ids=route_short_to_ids,
        route_id_to_short=route_id_to_short,
        trips_by_route=trips_by_route,
        trip_headsign=trip_headsign,
        trip_stops=trip_stops,
        stop_id_to_name=stop_id_to_name,
        stop_id_to_code=stop_id_to_code,
        stop_id_to_norm_name=stop_id_to_norm_name,
        updated_at=datetime.now().timestamp(),
        route_id_to_type=route_id_to_type,
        trip_departure_times=trip_departure_times,
        trip_service_id=trip_service_id,
        service_calendar=service_calendar,
        service_exceptions_by_date=service_exceptions_by_date,
    )


def load_gtfs_cache(cache_path: str, gtfs_url: str, timeout: int, ua: str) -> GtfsCache:
    cache_file = Path(cache_path)
    now = datetime.now().timestamp()
    if cache_file.exists():
        try:
            with open(cache_file, "r", encoding="utf-8") as file:
                payload = json.load(file)
            age = now - float(payload.get("updated_at", 0))
            if age < GTFS_TTL_SECONDS:
                for key in (
                    "route_id_to_type",
                    "trip_departure_times",
                    "trip_service_id",
                    "service_calendar",
                    "service_exceptions_by_date",
                ):
                    if key not in payload:
                        raise KeyError(f"GTFS cache missing {key}")
                return GtfsCache(
                    route_short_to_ids={k: list(v) for k, v in payload["route_short_to_ids"].items()},
                    route_id_to_short=payload["route_id_to_short"],
                    trips_by_route={k: list(v) for k, v in payload["trips_by_route"].items()},
                    trip_headsign=payload["trip_headsign"],
                    trip_stops={k: list(v) for k, v in payload["trip_stops"].items()},
                    stop_id_to_name=payload["stop_id_to_name"],
                    stop_id_to_code=payload["stop_id_to_code"],
                    stop_id_to_norm_name=payload["stop_id_to_norm_name"],
                    updated_at=float(payload.get("updated_at", now)),
                    route_id_to_type=payload["route_id_to_type"],
                    trip_departure_times={
                        k: list(v) for k, v in payload["trip_departure_times"].items()
                    },
                    trip_service_id=payload["trip_service_id"],
                    service_calendar=payload["service_calendar"],
                    service_exceptions_by_date={
                        day: {sid: int(kind) for sid, kind in services.items()}
                        for day, services in payload["service_exceptions_by_date"].items()
                    },
                )
        except Exception as exc:
            LOG.debug("Failed to read GTFS cache, rebuilding. err=%s", exc)

    gtfs_bytes = http_get(gtfs_url, timeout=timeout, user_agent=ua)
    built = build_gtfs_cache(gtfs_bytes)
    write_json_file(
        cache_file,
        {
            "updated_at": built.updated_at,
            "route_short_to_ids": built.route_short_to_ids,
            "route_id_to_short": built.route_id_to_short,
            "trips_by_route": built.trips_by_route,
            "trip_headsign": built.trip_headsign,
            "trip_stops": built.trip_stops,
            "stop_id_to_name": built.stop_id_to_name,
            "stop_id_to_code": built.stop_id_to_code,
            "stop_id_to_norm_name": built.stop_id_to_norm_name,
            "route_id_to_type": built.route_id_to_type,
            "trip_departure_times": built.trip_departure_times,
            "trip_service_id": built.trip_service_id,
            "service_calendar": built.service_calendar,
            "service_exceptions_by_date": built.service_exceptions_by_date,
        },
    )
    return built


WEEKDAY_KEYS = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)


def service_active_on(gtfs: GtfsCache, service_id: str, service_date: date) -> bool:
    ymd = service_date.strftime("%Y%m%d")
    exception = gtfs.service_exceptions_by_date.get(ymd, {}).get(service_id)
    if exception is not None:
        return exception == 1

    calendar = gtfs.service_calendar.get(service_id)
    if not calendar:
        return False
    if not (calendar.get("start_date", "") <= ymd <= calendar.get("end_date", "")):
        return False
    return calendar.get(WEEKDAY_KEYS[service_date.weekday()]) == "1"


def gtfs_time_to_seconds(value: Any) -> Optional[int]:
    parts = str(value or "").strip().split(":")
    if len(parts) != 3:
        return None
    try:
        hours, minutes, seconds = (int(part) for part in parts)
    except ValueError:
        return None
    if hours < 0 or minutes < 0 or seconds < 0:
        return None
    return hours * 3600 + minutes * 60 + seconds


def gtfs_time_to_datetime(value: Any, service_date: date, now: datetime) -> Optional[datetime]:
    seconds = gtfs_time_to_seconds(value)
    if seconds is None:
        return None
    local_now = now.astimezone()
    local_midnight = local_now.replace(
        year=service_date.year,
        month=service_date.month,
        day=service_date.day,
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )
    return local_midnight + timedelta(seconds=seconds)


def gtfs_time_to_text(value: Any) -> str:
    seconds = gtfs_time_to_seconds(value)
    if seconds is None:
        return str(value or "")
    return seconds_since_midnight_to_text(seconds)


def load_transit_gtfs(config: Dict[str, Any]) -> GtfsCache:
    http_conf = config.get("http", {})
    timeout = int(http_conf.get("timeout_seconds", 20))
    ua = str(http_conf.get("user_agent", "HomeAssistant Tallinn Widgets"))
    transit_conf = config.get("transit", {})
    gtfs_url = str(transit_conf.get("gtfs_url"))
    gtfs_cache_path = str(
        transit_conf.get("gtfs_cache_path", "/tmp/tallinn_gtfs_cache.json")
    )
    if not gtfs_url:
        raise ValueError("Missing transit.gtfs_url in config")
    return load_gtfs_cache(gtfs_cache_path, gtfs_url, timeout, ua)


def resolve_favorite_stop(
    favorite: Dict[str, Any], gtfs: GtfsCache
) -> Optional[Dict[str, Any]]:
    explicit_stop_id = str(favorite.get("stop_id", "") or "").strip()
    if explicit_stop_id and explicit_stop_id in gtfs.stop_id_to_name:
        return {
            "stop_id": explicit_stop_id,
            "route_short_name": favorite.get("route_short_name", ""),
            "headsign": favorite.get("headsign", ""),
            "stop_name": gtfs.stop_id_to_name.get(explicit_stop_id, ""),
            "label": favorite.get("label", "") or gtfs.stop_id_to_name.get(explicit_stop_id, ""),
            "limit": int(favorite.get("limit", 0) or 0) or None,
        }

    target_route = normalize_text(favorite.get("route_short_name"))
    target_headsign = normalize_text(favorite.get("headsign"))
    target_stop = normalize_text(favorite.get("stop_name"))
    if not (target_route and target_headsign and target_stop):
        # Require route + direction + stop for consistent matching
        return None

    route_ids = gtfs.route_short_to_ids.get(target_route, [])
    if not route_ids:
        route_ids = [rid for rid, short in gtfs.route_id_to_short.items() if normalize_text(short) == target_route]
    if not route_ids:
        return None

    candidate_ids: List[str] = []
    for rid in route_ids:
        for trip_id in gtfs.trips_by_route.get(rid, []):
            trip_sign = normalize_text(gtfs.trip_headsign.get(trip_id, ""))
            if target_headsign and target_headsign not in trip_sign and trip_sign not in target_headsign:
                continue
            for stop_id in gtfs.trip_stops.get(trip_id, []):
                stop_name = gtfs.stop_id_to_norm_name.get(stop_id, "")
                if stop_name_match(target_stop, stop_name):
                    candidate_ids.append(stop_id)

    if candidate_ids:
        stop_id = sorted(set(candidate_ids), key=lambda sid: sid)[0]
        return {
            "stop_id": stop_id,
            "route_short_name": favorite.get("route_short_name", ""),
            "headsign": favorite.get("headsign", ""),
            "stop_name": gtfs.stop_id_to_name.get(stop_id, ""),
            "label": favorite.get("label", "") or gtfs.stop_id_to_name.get(stop_id, ""),
            "limit": int(favorite.get("limit", 0) or 0) or None,
        }

    return None


def scheduled_rows_for_favorite(
    gtfs: GtfsCache,
    stop_id: str,
    favorite: Dict[str, Any],
    now: datetime,
    limit: int,
) -> List[Dict[str, Any]]:
    """Build static GTFS schedule rows when the realtime stop board is empty."""

    route_filter = normalize_text(favorite.get("route_short_name"))
    headsign_filter = normalize_text(favorite.get("headsign"))
    route_ids = gtfs.route_short_to_ids.get(route_filter, []) if route_filter else []
    if not route_ids and route_filter:
        route_ids = [
            rid
            for rid, short in gtfs.route_id_to_short.items()
            if normalize_text(short) == route_filter
        ]
    if not route_ids:
        return []

    local_today = now.astimezone().date()
    service_dates = (
        local_today - timedelta(days=1),
        local_today,
        local_today + timedelta(days=1),
    )
    rows: List[Dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for route_id in route_ids:
        route_short = gtfs.route_id_to_short.get(route_id, "")
        for trip_id in gtfs.trips_by_route.get(route_id, []):
            trip_sign = normalize_text(gtfs.trip_headsign.get(trip_id, ""))
            if (
                headsign_filter
                and trip_sign
                and headsign_filter not in trip_sign
                and trip_sign not in headsign_filter
            ):
                continue

            service_id = gtfs.trip_service_id.get(trip_id, "")
            if not service_id:
                continue

            stop_ids = gtfs.trip_stops.get(trip_id, [])
            departure_times = gtfs.trip_departure_times.get(trip_id, [])
            for idx, trip_stop_id in enumerate(stop_ids):
                if trip_stop_id != stop_id or idx >= len(departure_times):
                    continue
                departure_time = departure_times[idx]
                for service_date in service_dates:
                    if not service_active_on(gtfs, service_id, service_date):
                        continue
                    departure_at = gtfs_time_to_datetime(departure_time, service_date, now)
                    if departure_at is None:
                        continue
                    if departure_at < now - timedelta(minutes=1):
                        continue
                    seen_key = (trip_id, departure_at.isoformat())
                    if seen_key in seen:
                        continue
                    seen.add(seen_key)
                    rows.append(
                        {
                            "route": route_short,
                            "headsign": gtfs.trip_headsign.get(trip_id, ""),
                            "raw_time": gtfs_time_to_text(departure_time),
                            "departure_at": departure_at.isoformat(),
                            "in_minutes": minutes_until(departure_at, now),
                            "source": {
                                "kind": "gtfs_schedule",
                                "trip_id": trip_id,
                                "service_id": service_id,
                                "service_date": service_date.isoformat(),
                            },
                        }
                    )

    rows.sort(key=lambda row: row.get("departure_at", ""))
    return rows[:limit]


def _public_stop_modes(gtfs: GtfsCache) -> Dict[str, set[str]]:
    modes_by_stop: Dict[str, set[str]] = defaultdict(set)
    for route_id, trip_ids in gtfs.trips_by_route.items():
        mode = PUBLIC_TRANSIT_ROUTE_TYPES.get(gtfs.route_id_to_type.get(route_id, ""))
        if not mode:
            continue
        for trip_id in trip_ids:
            for stop_id in gtfs.trip_stops.get(trip_id, []):
                modes_by_stop[stop_id].add(mode)
    return modes_by_stop


def build_transit_station_list(
    config: Dict[str, Any], query: str = "", limit: int = 30, mode: str = ""
) -> Dict[str, Any]:
    now = datetime.now().astimezone()
    normalized_query = normalize_text(query)
    mode_filter = normalize_text(mode)
    if mode_filter and mode_filter not in PUBLIC_TRANSIT_ROUTE_TYPES.values():
        mode_filter = ""
    if not normalized_query:
        return {
            "status": "ok",
            "updated_at": now.isoformat(),
            "stations": [],
            "count": 0,
        }

    gtfs = load_transit_gtfs(config)
    modes_by_stop = _public_stop_modes(gtfs)
    stations: Dict[str, Dict[str, Any]] = {}
    for stop_id, modes in modes_by_stop.items():
        if mode_filter and mode_filter not in modes:
            continue
        name = gtfs.stop_id_to_name.get(stop_id, "")
        normalized_name = gtfs.stop_id_to_norm_name.get(stop_id, "")
        if not name or normalized_query not in normalized_name:
            continue
        station = stations.setdefault(
            normalized_name,
            {"id": name, "name": name, "modes": set(), "stop_count": 0},
        )
        station["modes"].update(modes)
        station["stop_count"] += 1

    rows = sorted(
        (
            {
                "id": item["id"],
                "name": item["name"],
                "modes": sorted(item["modes"]),
                "stop_count": item["stop_count"],
            }
            for item in stations.values()
        ),
        key=lambda item: normalize_text(item["name"]),
    )[: max(1, int(limit))]

    return {
        "status": "ok",
        "updated_at": now.isoformat(),
        "stations": rows,
        "count": len(rows),
    }


def _format_due(minutes: int) -> str:
    if minutes <= 0:
        return "now"
    return f"{minutes} min"


def build_transit_station_departures(
    config: Dict[str, Any],
    station: str,
    window_minutes: int = 60,
    limit: int = 80,
    mode: str = "",
) -> Dict[str, Any]:
    now = datetime.now().astimezone()
    station_norm = normalize_text(station)
    mode_filter = normalize_text(mode)
    if mode_filter and mode_filter not in PUBLIC_TRANSIT_ROUTE_TYPES.values():
        mode_filter = ""
    if not station_norm:
        return {
            "status": "error",
            "updated_at": now.isoformat(),
            "errors": ["Missing station"],
            "payload": {},
        }

    gtfs = load_transit_gtfs(config)
    modes_by_stop = _public_stop_modes(gtfs)
    stop_ids = {
        stop_id
        for stop_id, stop_norm in gtfs.stop_id_to_norm_name.items()
        if stop_norm == station_norm and stop_id in modes_by_stop
    }
    if not stop_ids:
        return {
            "status": "error",
            "updated_at": now.isoformat(),
            "errors": [f"Unknown public transit station: {station}"],
            "payload": {"station": station, "departures": []},
        }

    until = now + timedelta(minutes=max(1, int(window_minutes)))
    service_dates = (
        now.date() - timedelta(days=1),
        now.date(),
        now.date() + timedelta(days=1),
    )
    rows: List[Dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    for route_id, trip_ids in gtfs.trips_by_route.items():
        mode = PUBLIC_TRANSIT_ROUTE_TYPES.get(gtfs.route_id_to_type.get(route_id, ""))
        if not mode:
            continue
        if mode_filter and mode != mode_filter:
            continue
        route_short = gtfs.route_id_to_short.get(route_id, "")
        for trip_id in trip_ids:
            service_id = gtfs.trip_service_id.get(trip_id, "")
            if not service_id:
                continue
            stop_sequence = gtfs.trip_stops.get(trip_id, [])
            departure_times = gtfs.trip_departure_times.get(trip_id, [])
            for idx, stop_id in enumerate(stop_sequence):
                if stop_id not in stop_ids or idx >= len(departure_times):
                    continue
                departure_time = departure_times[idx]
                for service_date in service_dates:
                    if not service_active_on(gtfs, service_id, service_date):
                        continue
                    departure_at = gtfs_time_to_datetime(departure_time, service_date, now)
                    if departure_at is None or departure_at < now - timedelta(minutes=1):
                        continue
                    if departure_at > until:
                        continue
                    seen_key = (trip_id, stop_id, departure_at.isoformat())
                    if seen_key in seen:
                        continue
                    seen.add(seen_key)
                    in_minutes = minutes_until(departure_at, now)
                    rows.append(
                        {
                            "mode": mode,
                            "route": route_short,
                            "direction": gtfs.trip_headsign.get(trip_id, ""),
                            "time": gtfs_time_to_text(departure_time),
                            "departure_at": departure_at.isoformat(),
                            "in_minutes": in_minutes,
                            "due": _format_due(in_minutes),
                            "stop_id": stop_id,
                            "stop_name": gtfs.stop_id_to_name.get(stop_id, station),
                            "stop_code": gtfs.stop_id_to_code.get(stop_id, ""),
                            "trip_id": trip_id,
                            "data_source": "gtfs_schedule",
                        }
                    )

    rows.sort(key=lambda item: (item["departure_at"], item["route"], item["direction"]))
    rows = rows[: max(1, int(limit))]
    return {
        "status": "ok",
        "updated_at": now.isoformat(),
        "payload": {
            "station": station,
            "window_minutes": int(window_minutes),
            "departures": rows,
            "count": len(rows),
            "data_source": "gtfs_schedule",
        },
        "errors": [],
    }


def build_transit_payload(config: Dict[str, Any]) -> Dict[str, Any]:
    http_conf = config.get("http", {})
    timeout = int(http_conf.get("timeout_seconds", 20))
    ua = str(http_conf.get("user_agent", "HomeAssistant Tallinn Widgets"))
    transit_conf = config.get("transit", {})
    favorites = list(transit_conf.get("favorites", []))[:5]
    default_limit = int(transit_conf.get("default_limit", 5))
    if not transit_conf.get("gtfs_url"):
        return {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "status": "error",
            "errors": ["Missing transit.gtfs_url in config"],
            "payload": {},
        }

    gtfs = load_transit_gtfs(config)
    resolved: List[Dict[str, Any]] = []
    errors: List[str] = []
    stop_requests: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

    for favorite in favorites:
        resolved_item = resolve_favorite_stop(favorite, gtfs)
        if not resolved_item:
            errors.append(
                f"Could not resolve stop_id for '{favorite.get('stop_name')}' on route '{favorite.get('route_short_name')}' direction '{favorite.get('headsign')}'"
            )
            continue
        resolved.append(resolved_item)
        stop_requests[resolved_item["stop_id"]].append(
            {
                "route_short_name": resolved_item.get("route_short_name", ""),
                "headsign": resolved_item.get("headsign", ""),
                "label": resolved_item.get("label", ""),
                "limit": resolved_item.get("limit"),
            }
        )

    departures_payload: List[Dict[str, Any]] = []
    now = datetime.now().astimezone()
    for stop_id, filters in stop_requests.items():
        try:
            raw = http_get_text(STOP_API.format(stop_id), timeout, ua)
        except Exception as exc:
            errors.append(f"Failed stop-board request for stop {stop_id}: {exc}")
            continue
        parsed_rows = parse_departure_rows(raw, now=now)
        for idx, flt in enumerate(filters):
            filtered = filter_rows_for_favorite(parsed_rows, flt)
            limit = flt.get("limit") or default_limit
            selected = sorted(filtered, key=lambda item: item.get("departure_at", ""))[: int(limit)]
            data_source = "realtime"
            if not selected:
                selected = scheduled_rows_for_favorite(
                    gtfs,
                    stop_id,
                    flt,
                    now,
                    int(limit),
                )
                if selected:
                    data_source = "gtfs_schedule"
            label = flt.get("label") or f"Stop {stop_id}"
            dep_rows = []
            for row in selected:
                if isinstance(row.get("in_minutes"), int):
                    min_text = f"{row['in_minutes']} min"
                else:
                    min_text = "n/a"
                dep_rows.append(
                    {
                        "route": row.get("route", ""),
                        "headsign": row.get("headsign", ""),
                        "time": row.get("raw_time", ""),
                        "departure_at": row.get("departure_at", ""),
                        "in_minutes": min_text,
                    }
                )
            departures_payload.append(
                {
                    "stop_id": stop_id,
                    "label": label,
                    "route_filter": flt.get("route_short_name", ""),
                    "headsign_filter": flt.get("headsign", ""),
                    "resolved_stop_name": gtfs.stop_id_to_name.get(stop_id, ""),
                    "data_source": data_source,
                    "departures": dep_rows,
                }
            )

    return {
        "status": "ok" if not errors else "partial",
        "updated_at": now.isoformat(),
        "payload": {
            "resolved_favorites": resolved,
            "departures": departures_payload,
            "count": len(departures_payload),
        },
        "errors": errors,
    }


def parse_elapsed_minutes(reference: str, actual: str) -> str:
    ref_dt = parse_time_to_datetime(reference, fallback=None)
    act_dt = parse_time_to_datetime(actual, fallback=None)
    if not ref_dt or not act_dt:
        return ""
    delta = int((act_dt - ref_dt).total_seconds() // 60)
    if delta > 0:
        return f"+{delta}"
    if delta < 0:
        return f"{delta}"
    return "0"


def build_elron_station_list(
    query: str = "", limit: int = 50, timeout: int = 20, ua: str = "HomeAssistant Tallinn Widgets"
) -> Dict[str, Any]:
    now = datetime.now().astimezone()
    payload = http_get_json(ELRON_STOPS_URL, timeout, ua)
    stops = payload.get("data") if isinstance(payload, dict) else None
    normalized_query = normalize_text(query)
    rows = []
    if isinstance(stops, list):
        for item in stops:
            if not isinstance(item, dict):
                continue
            name = str(item.get("peatus", "")).strip()
            if not name:
                continue
            if normalized_query and normalized_query not in normalize_text(name):
                continue
            rows.append(
                {
                    "id": name,
                    "name": name,
                    "latitude": item.get("latitude"),
                    "longitude": item.get("longitude"),
                    "message": str(item.get("teade", "") or "").strip(),
                }
            )

    rows.sort(key=lambda item: normalize_text(item["name"]))
    rows = rows[: max(1, int(limit))]
    return {
        "status": "ok",
        "updated_at": now.isoformat(),
        "stations": rows,
        "count": len(rows),
    }


def _parse_local_station_time(
    station_date: str, station_time: str, now: datetime
) -> Optional[datetime]:
    if not station_date or not station_time:
        return None
    try:
        parsed = datetime.strptime(
            f"{station_date} {station_time}", "%Y-%m-%d %H:%M"
        )
    except ValueError:
        return None
    return parsed.replace(tzinfo=now.astimezone().tzinfo)


def build_elron_station_departures(
    station: str,
    window_minutes: int = 60,
    limit: int = 80,
    timeout: int = 20,
    ua: str = "HomeAssistant Tallinn Widgets",
) -> Dict[str, Any]:
    now = datetime.now().astimezone()
    if not station.strip():
        return {
            "status": "error",
            "updated_at": now.isoformat(),
            "errors": ["Missing station"],
            "payload": {},
        }

    url = ELRON_STOP_URL.format(urllib.parse.quote(station.strip(), safe=""))
    payload = http_get_json(url, timeout, ua)
    raw_rows = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(raw_rows, list):
        return {
            "status": "error",
            "updated_at": now.isoformat(),
            "errors": [f"Unexpected Elron station payload for {station}"],
            "payload": {"station": station, "departures": []},
        }

    until = now + timedelta(minutes=max(1, int(window_minutes)))
    rows: List[Dict[str, Any]] = []
    for item in raw_rows:
        if not isinstance(item, dict):
            continue
        planned = str(item.get("plaaniline_aeg", "")).strip()
        actual = str(item.get("tegelik_aeg", "")).strip()
        station_date = str(item.get("kuupaev", "")).strip()
        departure_at = _parse_local_station_time(station_date, actual or planned, now)
        if departure_at is None:
            continue
        if departure_at < now - timedelta(minutes=1) or departure_at > until:
            continue
        in_minutes = minutes_until(departure_at, now)
        rows.append(
            {
                "trip": str(item.get("reis", "")).strip(),
                "line": str(item.get("liin", "")).strip(),
                "direction": str(item.get("sihtjaam", "")).strip(),
                "time": actual or planned,
                "planned": planned,
                "actual": actual,
                "departure_at": departure_at.isoformat(),
                "in_minutes": in_minutes,
                "due": _format_due(in_minutes),
                "platform": str(item.get("peatuskoht", "")).strip(),
                "platform_changed": str(item.get("peatuskoht_muutunud", "")).strip(),
                "status": str(item.get("reisi_staatus", "")).strip(),
                "message": str(item.get("lisateade", "") or item.get("pohjus_teade", "") or "").strip(),
                "data_source": "elron_live_map",
            }
        )

    rows.sort(key=lambda item: (item["departure_at"], item["line"], item["trip"]))
    rows = rows[: max(1, int(limit))]
    return {
        "status": "ok",
        "updated_at": now.isoformat(),
        "payload": {
            "station": station,
            "window_minutes": int(window_minutes),
            "departures": rows,
            "count": len(rows),
            "data_source": "elron_live_map",
        },
        "errors": [],
    }


def build_elron_payload(config: Dict[str, Any]) -> Dict[str, Any]:
    http_conf = config.get("http", {})
    timeout = int(http_conf.get("timeout_seconds", 20))
    ua = str(http_conf.get("user_agent", "HomeAssistant Tallinn Widgets"))
    train_conf = config.get("trains", {})
    default_limit = int(train_conf.get("default_limit", 20))
    trips = train_conf.get("trips", [])
    now_iso = datetime.now(timezone.utc).isoformat()
    errors: List[str] = []
    rows_payload: List[Dict[str, Any]] = []

    for trip in list(trips)[:5]:
        trip_id = trip.get("trip_id")
        if trip_id is None:
            errors.append("Train favorite is missing trip_id")
            continue
        try:
            payload = http_get_json(ELRON_TRIP_URL.format(int(trip_id)), timeout, ua)
        except Exception as exc:
            errors.append(f"Failed to fetch trip {trip_id}: {exc}")
            continue

        stops_raw = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(stops_raw, list):
            errors.append(f"Unexpected payload for trip {trip_id}")
            continue

        enriched = []
        for item in stops_raw:
            if not isinstance(item, dict):
                continue
            planned = str(item.get("plaaniline_aeg", "")).strip()
            actual = str(item.get("tegelik_aeg", "")).strip()
            enriched.append(
                {
                    "station": str(item.get("peatus", "")).strip(),
                    "planned": planned,
                    "actual": actual,
                    "delay": parse_elapsed_minutes(planned, actual),
                }
            )

        limit = int(trip.get("limit", default_limit))
        rows_payload.append(
            {
                "trip_id": trip_id,
                "label": str(trip.get("label", f"Trip {trip_id}")),
                "station_count": len(enriched),
                "stations": enriched[: int(limit)],
            }
        )

    return {
        "status": "ok" if not errors else "partial",
        "updated_at": now_iso,
        "payload": {"trips": rows_payload},
        "errors": errors,
    }
