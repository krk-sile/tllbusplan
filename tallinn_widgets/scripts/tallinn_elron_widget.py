#!/usr/bin/env python3
"""Build payload for the Elron trip dashboard widget."""

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

import os

from tallinn_widget_lib import build_elron_payload, read_json_file


def resolve_config_path(explicit: Optional[str]) -> Path:
    if explicit:
        return Path(explicit)

    explicit_env = os.getenv("TALLINN_WIDGETS_CONFIG")
    if explicit_env:
        return Path(explicit_env)

    candidates = [
        Path("/config/tallinn_widgets/config.json"),
        Path(__file__).resolve().parent.parent / "config.json",
        Path(".") / "config.json",
    ]

    for candidate in candidates:
        if candidate.exists():
            return candidate

    return candidates[0]


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Elron trip widget payload")
    parser.add_argument(
        "--config",
        required=False,
        help="Optional path to JSON config.",
    )
    args = parser.parse_args()

    config_path = resolve_config_path(args.config)
    if not config_path.exists():
        output = {
            "status": "error",
            "updated_at": "",
            "errors": [f"Config not found at {config_path}"],
            "payload": {},
        }
        print(json.dumps(output, ensure_ascii=False))
        return 1

    conf = read_json_file(config_path)
    result = build_elron_payload(conf)
    result.setdefault("updated_at", "")
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("status") in {"ok", "partial"} else 1


if __name__ == "__main__":
    sys.exit(main())
