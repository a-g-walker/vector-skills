#!/usr/bin/env python3
"""Rebuild index.json (the catalogue robots read) from skills/*.json.

    python3 tools/build_index.py           # write index.json
    python3 tools/build_index.py --check   # exit 1 if index.json is out of date
"""

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine"))
import trick_engine as te  # noqa: E402


def build():
    entries = []
    for path in sorted((ROOT / "skills").glob("*.json")):
        raw = path.read_bytes()
        data = json.loads(raw)
        plan = te.prepare(data, render=False)
        entries.append({
            "name": plan.name,
            "title": data.get("title", plan.name),
            "description": data.get("description", ""),
            "author": data.get("author", ""),
            "file": f"skills/{path.name}",
            "seconds": round(plan.seconds),
            "moves": plan.needs_floor,
            "endings": te.variants(data),
            "sha256": hashlib.sha256(raw).hexdigest(),
        })
    return json.dumps({"format": "d5-skills-index", "version": 1, "skills": entries}, indent=2) + "\n"


if __name__ == "__main__":
    try:
        text = build()
    except (json.JSONDecodeError, UnicodeDecodeError, te.TrickError) as e:
        print(f"can't build index.json until every skill is valid ({e}); see tools/check_skills.py")
        sys.exit(1)
    index = ROOT / "index.json"
    if "--check" in sys.argv:
        if not index.exists() or index.read_text() != text:
            print("index.json is out of date: run python3 tools/build_index.py and commit it")
            sys.exit(1)
        print("index.json is up to date")
    else:
        index.write_text(text)
        print(f"wrote index.json ({text.count('\"name\"')} skills)")
