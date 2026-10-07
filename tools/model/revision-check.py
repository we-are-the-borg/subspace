#!/usr/bin/env python3
"""Every changed mapping document has a higher `revision` than in <base>.

    python3 tools/model/revision-check.py origin/main

Apps pick the higher revision of $ROOT/model/<source>.json and their bundled
copy (contract §12), so a change without a bump could be shadowed by an older
document. CI runs this on pull requests. Test tooling, never part of the hook.
"""

import json
import pathlib
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent.parent


def at_base(base, path):
    shown = subprocess.run(["git", "-C", str(REPO), "show", f"{base}:{path}"],
                           capture_output=True, text=True)
    return json.loads(shown.stdout) if shown.returncode == 0 else None


def main():
    if len(sys.argv) != 2:
        sys.exit("usage: revision-check.py <base ref>")
    base = sys.argv[1]
    failed = False
    for path in sorted(REPO.glob("model/*.json")):
        rel = path.relative_to(REPO).as_posix()
        new = json.loads(path.read_text(encoding="utf-8"))
        old = at_base(base, rel)
        if old is None or old == new:
            print(f"ok   {rel}: {'new' if old is None else 'unchanged'}, revision {new.get('revision')}")
            continue
        if not isinstance(new.get("revision"), int) or new["revision"] <= old.get("revision", 0):
            print(f"FAIL {rel} changed but its revision {new.get('revision')} is not above {old.get('revision')} in {base}")
            failed = True
        else:
            print(f"ok   {rel}: revision {old.get('revision')} -> {new['revision']}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
