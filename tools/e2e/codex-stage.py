#!/usr/bin/env python3
"""Stage the working Codex adapter in a disposable local marketplace.

No Codex processes, configuration writes, or captures are started. Synthetic
versions only affect this disposable copy, never release-owned repository files.
"""

import argparse
import json
import shutil
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    parser.add_argument(
        "--revision", choices=["baseline", "version-only", "changed-hook"],
        default="baseline",
    )
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[2]
    destination = args.destination.expanduser().resolve()
    if destination == repo or repo in destination.parents:
        parser.error("stage outside the repository")
    if destination.exists():
        parser.error("destination must not exist; use a fresh disposable directory")

    adapter = destination / "codex"
    shutil.copytree(repo / "adapters/codex", adapter)
    manifest_path = adapter / ".codex-plugin/plugin.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["version"] = {
        "baseline": "0.0.0", "version-only": "0.0.1", "changed-hook": "0.0.2",
    }[args.revision]
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    if args.revision == "changed-hook":
        hooks_path = adapter / "hooks/hooks.json"
        hooks = json.loads(hooks_path.read_text())
        # A harmless trailing space changes the definition hash without
        # changing the command's behavior or adding hook output.
        hooks["hooks"]["SessionStart"][0]["hooks"][0]["command"] += " "
        hooks_path.write_text(json.dumps(hooks, indent=2) + "\n")

    marketplace = json.loads((repo / "tools/dist/codex/.agents/plugins/marketplace.json").read_text())
    marketplace["plugins"][0]["source"] = "./codex"
    catalog = destination / ".agents/plugins/marketplace.json"
    catalog.parent.mkdir(parents=True)
    catalog.write_text(json.dumps(marketplace, indent=2) + "\n")
    print(destination)


if __name__ == "__main__":
    main()
