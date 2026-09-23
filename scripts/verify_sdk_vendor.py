"""Verify the checked-in official SDK and relay against the pinned file manifest."""

import hashlib
import json
from pathlib import Path

root = Path(__file__).resolve().parent.parent / "vendor/dimos-web"
manifest = json.loads((root.parent / "dimos-web-source.json").read_text())
errors = []
for name, expected in manifest["files"].items():
    path = root / name
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        errors.append(name)
if errors:
    raise SystemExit("Changed or missing upstream files: " + ", ".join(errors))
print(f"Verified {len(manifest['files'])} upstream files at {manifest['revision']}")
