"""Validate package metadata against KiCad's PCM schema.

    python3 tools/validate_pcm.py [package.zip | metadata.json] [--schema path-or-url]

Needs `pip install jsonschema`.  The schema defaults to KiCad's published v1 schema.
"""

import argparse
import json
import os
import sys
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMA_URL = "https://go.kicad.org/pcm/schemas/v1"


def load_schema(src):
    if os.path.isfile(src):
        with open(src, encoding="utf-8") as f:
            return json.load(f)
    # gitlab.com (where the URL redirects) rejects Python's default User-Agent
    req = urllib.request.Request(src, headers={"User-Agent": "curl/8 kicad-autoled-ci"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def load_metadata(path):
    if path.endswith(".zip"):
        with zipfile.ZipFile(path) as z:
            return json.loads(z.read("metadata.json").decode("utf-8"))
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main(argv=None):
    import jsonschema

    ap = argparse.ArgumentParser(description="Validate KiCad PCM metadata")
    ap.add_argument("target", nargs="?", default=os.path.join(ROOT, "pcm", "metadata.json"))
    ap.add_argument("--schema", default=SCHEMA_URL)
    args = ap.parse_args(argv)

    schema = load_schema(args.schema)
    meta = load_metadata(args.target)
    jsonschema.validate(meta, dict(schema, **{"$ref": "#/definitions/Package"}))
    if len(meta["versions"]) != 1:
        raise SystemExit("A package file must describe exactly one version")
    print("%s: valid (%s %s)" % (args.target, meta["identifier"], meta["versions"][0]["version"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
