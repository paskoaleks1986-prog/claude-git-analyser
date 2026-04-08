"""YAML report exporter."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import yaml


def export(data: dict, output_path: str) -> str:
    """Write full analysis to a YAML file. Returns the file path."""
    # Add generation timestamp
    data.setdefault("meta", {})["generated_at"] = datetime.now(tz=timezone.utc).isoformat()
    data["meta"]["tool"] = "claude-check-repo"
    data["meta"]["version"] = "0.1.0"

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(
            data,
            f,
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
            indent=2,
        )

    return str(path.resolve())