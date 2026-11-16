#!/usr/bin/env python3
"""Generate a local CycloneDX dependency inventory; never contacts a service.

This is a component inventory, not a vulnerability scan or a resolver lock.
Run in the exact release environment and scan the resulting SBOM/image with
the organization's scanner. Node entries use the committed lockfiles.
"""

import argparse
import importlib.metadata
import json
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote


def inventory(root: Path) -> dict:
    components = {}
    for distribution in importlib.metadata.distributions():
        name = distribution.metadata.get("Name")
        if not name:
            continue
        version = distribution.version
        purl = f"pkg:pypi/{name.lower().replace('_', '-')}@{version}"
        components[purl] = {
            "type": "library",
            "name": name,
            "version": version,
            "purl": purl,
        }
    for app in ("console", "portal"):
        lock = root / app / "package-lock.json"
        if not lock.is_file():
            continue
        data = json.loads(lock.read_text())
        for location, package in data.get("packages", {}).items():
            if "node_modules/" not in location or not package.get("version"):
                continue
            name = location.rsplit("node_modules/", 1)[-1]
            version = package["version"]
            purl = f"pkg:npm/{quote(name, safe='/')}@{version}"
            components[purl] = {
                "type": "library",
                "name": name,
                "version": version,
                "purl": purl,
            }
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    dirty = bool(
        subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=root,
            text=True,
            capture_output=True,
            check=True,
        ).stdout.strip()
    )
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "version": 1,
        "serialNumber": f"urn:uuid:{uuid.uuid4()}",
        "metadata": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "properties": [
                {"name": "qwenpaw:source-commit", "value": commit},
                {"name": "qwenpaw:worktree-dirty", "value": str(dirty).lower()},
                {
                    "name": "qwenpaw:scope",
                    "value": "current Python environment and console/portal npm locks; OS/image/remote components require separate inventory",
                },
            ],
        },
        "components": sorted(components.values(), key=lambda item: item["purl"]),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result = inventory(Path(__file__).resolve().parents[2])
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(f"Components: {len(result['components'])}; output: {args.output}")
