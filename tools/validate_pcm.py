"""Validate the package against KiCad's PCM schema and add-on publishing rules.

    python3 tools/validate_pcm.py [dist/AutoLED-x.y.z.zip] [--submit dist/metadata-submit.json]
                                  [--schema path-or-url]

Checks (https://dev-docs.kicad.org/en/addons/):
- metadata.json (inside the zip, or pcm/metadata.json) validates against the PCM schema
- description <= 150 chars, identifier format, $schema present, exactly one version
- the archive has only metadata.json, resources/ and plugins/, and no download_* fields
- with --submit: download_url / sha256 / sizes are present and match the zip

Needs `pip install jsonschema`.  The schema defaults to KiCad's published v1 schema.
"""

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMA_URL = "https://go.kicad.org/pcm/schemas/v1"
IDENTIFIER_RE = re.compile(r"^[a-zA-Z][-a-zA-Z0-9.]{0,48}[a-zA-Z0-9]$")
DOWNLOAD_FIELDS = ("download_url", "download_sha256", "download_size", "install_size")


def load_schema(src):
    if os.path.isfile(src):
        with open(src, encoding="utf-8") as f:
            return json.load(f)
    # gitlab.com (where the URL redirects) rejects Python's default User-Agent
    req = urllib.request.Request(src, headers={"User-Agent": "curl/8 kicad-autoled-ci"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def fail(msg):
    raise SystemExit("INVALID: " + msg)


def check_package(meta, schema, where):
    import jsonschema
    jsonschema.validate(meta, dict(schema, **{"$ref": "#/definitions/Package"}))
    if "$schema" not in meta:
        fail("%s: $schema is required" % where)
    if len(meta["description"]) > 150:
        fail("%s: description is %d chars (max 150)" % (where, len(meta["description"])))
    if not IDENTIFIER_RE.match(meta["identifier"]):
        fail("%s: identifier %r must be 2-50 chars, start with a letter, end with a letter "
             "or digit" % (where, meta["identifier"]))
    if len(meta["versions"]) != 1:
        fail("%s: exactly one version expected" % where)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Validate KiCad PCM package metadata")
    ap.add_argument("target", nargs="?", default=os.path.join(ROOT, "pcm", "metadata.json"),
                    help="package zip or metadata.json")
    ap.add_argument("--submit", help="metadata-submit.json to check against the zip")
    ap.add_argument("--schema", default=SCHEMA_URL)
    args = ap.parse_args(argv)
    schema = load_schema(args.schema)

    is_zip = args.target.endswith(".zip")
    if is_zip:
        with zipfile.ZipFile(args.target) as z:
            names = z.namelist()
            meta = json.loads(z.read("metadata.json").decode("utf-8"))
            install_size = sum(i.file_size for i in z.infolist())
        extra = [n for n in names if n != "metadata.json"
                 and not n.startswith(("resources/", "plugins/"))]
        if extra:
            fail("unexpected files in the archive: %s" % ", ".join(extra))
        if "plugins/__init__.py" not in names:
            fail("plugins/__init__.py missing")
    else:
        with open(args.target, encoding="utf-8") as f:
            meta = json.load(f)
    check_package(meta, schema, args.target)
    leaked = [k for k in DOWNLOAD_FIELDS if k in meta["versions"][0]]
    if leaked:
        fail("%s must not contain %s (only the submitted metadata does)" % (args.target, leaked))
    print("%s: valid (%s %s)" % (args.target, meta["identifier"], meta["versions"][0]["version"]))

    if args.submit:
        if not is_zip:
            fail("--submit needs the package zip as target")
        with open(args.submit, encoding="utf-8") as f:
            sub = json.load(f)
        check_package(sub, schema, args.submit)
        ver = sub["versions"][0]
        missing = [k for k in DOWNLOAD_FIELDS if k not in ver]
        if missing:
            fail("%s: missing %s" % (args.submit, missing))
        with open(args.target, "rb") as f:
            data = f.read()
        if ver["download_sha256"] != hashlib.sha256(data).hexdigest():
            fail("download_sha256 does not match %s" % args.target)
        if ver["download_size"] != len(data):
            fail("download_size does not match %s" % args.target)
        if ver["install_size"] != install_size:
            fail("install_size %d != %d" % (ver["install_size"], install_size))
        strip = dict(ver)
        for k in DOWNLOAD_FIELDS:
            strip.pop(k)
        if dict(sub, versions=[strip]) != meta:
            fail("%s differs from the metadata inside the zip" % args.submit)
        print("%s: valid, matches the zip (%s)" % (args.submit, ver["download_url"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
