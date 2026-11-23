"""Runtime configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _as_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    host: str = "0.0.0.0"
    port: int = 8099
    ingress_ip_check: bool = True

    @classmethod
    def from_environment(cls) -> "Settings":
        return cls(
            data_dir=Path(os.environ.get("INVENTORY_DATA_DIR", "/data")),
            host=os.environ.get("INVENTORY_HOST", "0.0.0.0"),
            port=int(os.environ.get("INVENTORY_PORT", "8099")),
            ingress_ip_check=not _as_bool(
                os.environ.get("INVENTORY_ALLOW_DIRECT_ACCESS"), False
            ),
        )
