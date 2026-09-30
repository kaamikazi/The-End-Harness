"""Read-only file manifest for auditing the untouched external projects."""
import argparse
import hashlib
import json
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("root", type=Path)
parser.add_argument("output", type=Path)
args = parser.parse_args()
manifest = {}
for path in sorted(args.root.rglob("*")):
    if path.is_file() and ".git" not in path.relative_to(args.root).parts:
        manifest[path.relative_to(args.root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(json.dumps(manifest, sort_keys=True, indent=2), encoding="utf-8")
print(f"{len(manifest)} files; manifest SHA256 {hashlib.sha256(args.output.read_bytes()).hexdigest()}")
