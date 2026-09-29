"""Build a Plugin and Content Manager package: dist/AutoLED-<version>.zip

    python3 tools/build_pcm.py [--version 1.2.3]

Install it in KiCad via Plugin and Content Manager -> Install from File...
--version (a leading "v" is allowed, e.g. a git tag) overrides the version in
pcm/metadata.json inside the package.  A .sha256 file is written next to the zip.
"""

import argparse
import hashlib
import json
import os
import re
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERSION_RE = re.compile(r"^\d{1,4}(\.\d{1,4}(\.\d{1,6})?)?$")


def build(version=None, dist=None):
    with open(os.path.join(ROOT, "pcm", "metadata.json"), encoding="utf-8") as f:
        meta = json.load(f)
    if version:
        version = version.lstrip("vV")
        if not VERSION_RE.match(version):
            raise SystemExit("Invalid version %r: expected major[.minor[.patch]]" % version)
        meta["versions"][0]["version"] = version
    version = meta["versions"][0]["version"]

    dist = dist or os.path.join(ROOT, "dist")
    os.makedirs(dist, exist_ok=True)
    out = os.path.join(dist, "AutoLED-%s.zip" % version)
    src = os.path.join(ROOT, "auto_led")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("metadata.json", json.dumps(meta, indent=2) + "\n")
        z.write(os.path.join(ROOT, "pcm", "icon.png"), "resources/icon.png")
        for name in sorted(os.listdir(src)):
            if name.endswith((".py", ".png")):
                z.write(os.path.join(src, name), "plugins/" + name)

    with zipfile.ZipFile(out) as z:
        names = set(z.namelist())
    for required in ("metadata.json", "resources/icon.png", "plugins/__init__.py", "plugins/plugin.py"):
        if required not in names:
            raise SystemExit("Package is missing " + required)

    with open(out, "rb") as f:
        digest = hashlib.sha256(f.read()).hexdigest()
    with open(out + ".sha256", "w") as f:
        f.write("%s  %s\n" % (digest, os.path.basename(out)))
    print("Wrote %s (%d bytes, sha256 %s)" % (out, os.path.getsize(out), digest))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--version", help="package version (e.g. 1.2.3 or v1.2.3)")
    ap.add_argument("--dist", help="output folder (default: dist/)")
    args = ap.parse_args(argv)
    path = build(args.version, args.dist)
    gh_out = os.environ.get("GITHUB_OUTPUT")
    if gh_out:
        with open(gh_out, "a") as f:
            f.write("zip=%s\n" % path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
