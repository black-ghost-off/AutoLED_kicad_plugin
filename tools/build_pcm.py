"""Build a Plugin and Content Manager package: dist/AutoLED-<version>.zip

Install it in KiCad via Plugin and Content Manager -> Install from File...
"""

import json
import os
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    with open(os.path.join(ROOT, "pcm", "metadata.json"), encoding="utf-8") as f:
        meta = json.load(f)
    version = meta["versions"][0]["version"]
    dist = os.path.join(ROOT, "dist")
    os.makedirs(dist, exist_ok=True)
    out = os.path.join(dist, "AutoLED-%s.zip" % version)
    src = os.path.join(ROOT, "auto_led")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(os.path.join(ROOT, "pcm", "metadata.json"), "metadata.json")
        z.write(os.path.join(ROOT, "pcm", "icon.png"), "resources/icon.png")
        for name in sorted(os.listdir(src)):
            if name.endswith((".py", ".png")):
                z.write(os.path.join(src, name), "plugins/" + name)
    print("Wrote " + out)


if __name__ == "__main__":
    main()
