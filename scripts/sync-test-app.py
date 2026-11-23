#!/usr/bin/env python3
"""Synchronize the test add-on with ha_inventory; keep its identity separate."""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "ha_inventory"
TEST = ROOT / "ha_inventory_test"
INDEPENDENT = {"config.yaml", "DOCS.md", "README.md"}


def runtime_files(folder: Path) -> dict[str, Path]:
    if not folder.is_dir():
        return {}
    return {
        str(p.relative_to(folder)): p
        for p in folder.rglob("*") if p.is_file()
        and not any(part in {"__pycache__", ".pytest_cache"} for part in p.relative_to(folder).parts)
        and p.name not in {".DS_Store"} and p.suffix not in {".pyc", ".pyo"}
        and str(p.relative_to(folder)) not in INDEPENDENT
    }


def test_config() -> str:
    text = (SOURCE / "config.yaml").read_text(encoding="utf-8")
    changes = {
        "name": '"HA Inventory TEST (v0.4)"',
        "version": '"0.4.0-test1"',
        "slug": '"ha-inventory-test"',
        "description": '"Isolierte Kassenbon-Test-App mit eigenem Datenbestand."',
        "url": '"https://github.com/foxifox56/ha-inventory/tree/development/v0.4-test-app/ha_inventory_test"',
        "boot": "manual",
    }
    for key, val in changes.items():
        text, count = re.subn(rf"(?m)^{re.escape(key)}:.*$", f"{key}: {val}", text)
        if count != 1:
            raise ValueError(f"Unexpected source config: {key}")
    return text


def check_or_sync(sync: bool) -> int:
    source = runtime_files(SOURCE)
    if sync:
        TEST.mkdir(parents=True, exist_ok=True)
        for name, path in source.items():
            target = TEST / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
        for name, path in runtime_files(TEST).items():
            if name not in source:
                path.unlink()
        (TEST / "config.yaml").write_text(test_config(), encoding="utf-8")
    target = runtime_files(TEST)
    issues = []
    for name in sorted(source.keys() | target.keys()):
        if name not in source or name not in target:
            issues.append(f"Dateibestand weicht ab: {name}")
        elif source[name].read_bytes() != target[name].read_bytes():
            issues.append(f"Dateiinhalt weicht ab: {name}")
    config = TEST / "config.yaml"
    if not config.is_file() or config.read_text(encoding="utf-8") != test_config():
        issues.append("Unsichere oder veraltete Test-Konfiguration")
    for doc in ("README.md", "DOCS.md"):
        if not (TEST / doc).is_file():
            issues.append(f"Test-Anleitung fehlt: {doc}")
    if issues:
        for issue in issues:
            print("ERROR:", issue, file=sys.stderr)
        print("Regenerieren: python scripts/sync-test-app.py --sync", file=sys.stderr)
        return 1
    print(f"OK: {len(source)} Dateien identisch, Test-App-Slug/Boot getrennt")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--check", action="store_true")
    group.add_argument("--sync", action="store_true")
    args = parser.parse_args()
    sys.exit(check_or_sync(args.sync))
