#!/usr/bin/env python3
"""Check every skill in skills/ (what the GitHub check runs on each pull request):

- valid JSON and a valid d5-trick (format, limits, every ending), via engine/trick_engine.py
- the "name" field matches the file name, and the file is at most 2 MB
- no "source" field (that's added by the robot that installs it)
- index.json is up to date
- with --previews DIR: an animated GIF of each skill (each ending), for reviewers

    python3 tools/check_skills.py [--previews previews]
"""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine"))
import trick_engine as te  # noqa: E402


def main(argv):
    previews = Path(argv[argv.index("--previews") + 1]) if "--previews" in argv else None
    if previews:
        previews.mkdir(parents=True, exist_ok=True)
    failures = 0
    for path in sorted((ROOT / "skills").glob("*")):
        problems = []
        if path.suffix != ".json":
            problems.append("only .json files belong in skills/")
        elif path.stat().st_size > te.LIMITS["file_bytes"]:
            problems.append(f"bigger than {te.LIMITS['file_bytes']} bytes")
        else:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict) and data.get("name") != path.stem:
                    problems.append(f'"name" is {data.get("name")!r} but the file is {path.name}')
                if isinstance(data, dict) and "source" in data:
                    problems.append('remove the "source" field (robots add it when installing)')
                if not problems:
                    line = te.describe(data)  # validates every ending
                    if previews:
                        for label in te.variants(data) or [""]:
                            gif = previews / (f"{path.stem}_{label}.gif" if label else f"{path.stem}.gif")
                            te.preview_gif(data, gif, label)
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                problems.append(f"not valid JSON: {e}")
            except te.TrickError as e:
                problems.append(str(e))
        if problems:
            failures += 1
            for p in problems:
                print(f"FAIL {path.name}: {p}")
        else:
            print(f"OK   {line}")
    index = subprocess.run([sys.executable, str(ROOT / "tools" / "build_index.py"), "--check"])
    if failures or index.returncode:
        print(f"\n{failures} skill(s) failed" + ("; index.json is out of date" if index.returncode else ""))
        return 1
    print("\nAll skills OK")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
