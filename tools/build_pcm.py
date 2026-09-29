"""Build a KiCad Plugin and Content Manager package.

    python3 tools/build_pcm.py [--version 1.2.3] [--download-url URL]

Writes to dist/:
  AutoLED-<version>.zip          the package (Install from File..., or a release asset)
  AutoLED-<version>.zip.sha256
  metadata-submit.json           metadata for the KiCad addons repository
                                 (gitlab.com/kicad/addons/metadata, packages/<identifier>/metadata.json)

--version (a leading "v" is allowed, e.g. a git tag) overrides the version in
pcm/metadata.json.  The download URL defaults to the GitHub release asset of that
version (tag v<version>).
"""

import argparse
import copy
import hashlib
import json
import os
import re
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERSION_RE = re.compile(r"^\d{1,4}(\.\d{1,4}(\.\d{1,6})?)?$")
DOWNLOAD_FIELDS = ("download_url", "download_sha256", "download_size", "install_size")
# fixed timestamp keeps the archive byte-identical between builds of the same sources
ZIP_DATE = (2020, 1, 1, 0, 0, 0)


def _add(z, arcname, data):
    info = zipfile.ZipInfo(arcname, ZIP_DATE)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    z.writestr(info, data)


def _read(path):
    with open(path, "rb") as f:
        return f.read()


def load_metadata(version=None):
    with open(os.path.join(ROOT, "pcm", "metadata.json"), encoding="utf-8") as f:
        meta = json.load(f)
    if len(meta["versions"]) != 1:
        raise SystemExit("pcm/metadata.json must contain exactly one version")
    ver = meta["versions"][0]
    for field in DOWNLOAD_FIELDS:
        ver.pop(field, None)  # never inside the archive
    if version:
        version = version.lstrip("vV")
        if not VERSION_RE.match(version):
            raise SystemExit("Invalid version %r: expected major[.minor[.patch]]" % version)
        ver["version"] = version
    return meta


def github_download_url(meta):
    repo = meta.get("resources", {}).get("Github", "").rstrip("/")
    if not repo:
        return None
    ver = meta["versions"][0]["version"]
    return "%s/releases/download/v%s/AutoLED-%s.zip" % (repo, ver, ver)


def build(version=None, dist=None, download_url=None):
    meta = load_metadata(version)
    version = meta["versions"][0]["version"]
    dist = dist or os.path.join(ROOT, "dist")
    os.makedirs(dist, exist_ok=True)
    out = os.path.join(dist, "AutoLED-%s.zip" % version)
    src = os.path.join(ROOT, "auto_led")

    files = [("metadata.json", (json.dumps(meta, indent=2) + "\n").encode("utf-8")),
             ("resources/icon.png", _read(os.path.join(ROOT, "pcm", "icon.png"))),
             ("plugins/LICENSE", _read(os.path.join(ROOT, "LICENSE")))]
    for name in sorted(os.listdir(src)):
        if name.endswith((".py", ".png")):
            files.append(("plugins/" + name, _read(os.path.join(src, name))))
    with zipfile.ZipFile(out, "w") as z:
        for arcname, data in files:
            _add(z, arcname, data)

    names = {a for a, _ in files}
    for required in ("metadata.json", "resources/icon.png", "plugins/__init__.py", "plugins/plugin.py"):
        if required not in names:
            raise SystemExit("Package is missing " + required)

    data = _read(out)
    digest = hashlib.sha256(data).hexdigest()
    with open(out + ".sha256", "w") as f:
        f.write("%s  %s\n" % (digest, os.path.basename(out)))

    # metadata for the KiCad addons repository: same package, version with download info
    submit = copy.deepcopy(meta)
    submit["versions"][0].update({
        "download_url": download_url or github_download_url(meta),
        "download_sha256": digest,
        "download_size": len(data),
        "install_size": sum(len(d) for _, d in files),
    })
    submit_path = os.path.join(dist, "metadata-submit.json")
    with open(submit_path, "w", encoding="utf-8") as f:
        json.dump(submit, f, indent=2)
        f.write("\n")

    print("Wrote %s (%d bytes, sha256 %s)" % (out, len(data), digest))
    print("Wrote %s (download_url %s)" % (submit_path, submit["versions"][0]["download_url"]))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build the KiCad PCM package")
    ap.add_argument("--version", help="package version (e.g. 1.2.3 or v1.2.3)")
    ap.add_argument("--dist", help="output folder (default: dist/)")
    ap.add_argument("--download-url", help="public URL of the zip (default: GitHub release asset)")
    args = ap.parse_args(argv)
    path = build(args.version, args.dist, args.download_url)
    gh_out = os.environ.get("GITHUB_OUTPUT")
    if gh_out:
        with open(gh_out, "a") as f:
            f.write("zip=%s\n" % path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
