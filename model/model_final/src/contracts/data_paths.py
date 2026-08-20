"""Resolve external dataset locations without coupling them to the code archive."""

from __future__ import annotations

import os
from pathlib import Path


DATA_DIR_ENV = "MODEL_VER3_DATA_DIR"


def resolve_data_dir(
    project_root: str | Path,
    data_dir: str | Path | None = None,
) -> Path:
    """Return an explicit, environment-provided, or project-local data directory."""
    configured = data_dir if data_dir is not None else os.environ.get(DATA_DIR_ENV)
    return Path(configured if configured is not None else Path(project_root) / "data").expanduser().resolve()
