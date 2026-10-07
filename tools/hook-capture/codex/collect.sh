#!/bin/sh
# Offline helper only; Python is not used by the logging hook.
exec python3 - "$(dirname "$0")" <<'PY'
import hashlib
import json
from pathlib import Path
import shutil
import sys

here = Path(sys.argv[1]).resolve()
out = here / "captures" / "transcripts"
out.mkdir(parents=True, exist_ok=True)
paths = set()
failed = False
for event in sorted((here / "captures" / "events").glob("*.json")):
    try:
        payload = json.loads(event.read_bytes())
        for key in ("transcript_path", "agent_transcript_path"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                path = Path(value)
                if not path.is_absolute():
                    raise ValueError(f"relative {key}: {value}")
                paths.add(path)
    except (OSError, ValueError, AttributeError) as error:
        print(f"cannot read {event.name}: {error}", file=sys.stderr)
        failed = True

for path in sorted(paths):
    try:
        # A path digest prevents same-basename rollouts from overwriting one
        # another. source.txt retains the original path for later curation.
        target = out / hashlib.sha256(str(path).encode()).hexdigest()
        if not path.is_file():
            raise FileNotFoundError(f"missing rollout: {path}")
        target.mkdir(exist_ok=True)
        shutil.copyfile(path, target / path.name)
        (target / "source.txt").write_text(str(path) + "\n")
        print(f"copied {path}")
    except OSError as error:
        print(str(error), file=sys.stderr)
        failed = True

sys.exit(1 if failed else 0)
PY
