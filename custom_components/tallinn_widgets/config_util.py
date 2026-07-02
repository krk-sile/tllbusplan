"""Config helpers for Tallinn Widgets."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .const import DEFAULT_CONFIG_PATH
from .tallinn_widget_lib import read_json_file


def resolve_config_path(configured: str) -> Path:
    """Resolve the widget config path with HACS-friendly fallbacks."""
    explicit = Path(configured).expanduser()
    if explicit.exists():
        return explicit

    default_path = Path(DEFAULT_CONFIG_PATH)
    candidates = [
        default_path,
        Path("/config/tallinn_widgets/config.example.json"),
    ]
    if explicit == default_path:
        candidates.append(Path(__file__).with_name("config.example.json"))

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return explicit


def read_widget_config(configured: str) -> dict[str, Any]:
    """Read the widget JSON config from the resolved path."""
    return read_json_file(resolve_config_path(configured))
