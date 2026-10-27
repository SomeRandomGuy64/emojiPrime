#!/usr/bin/env python3
"""Package the release files into dist/.

    build.py              the skill zip + the extension for every browser in extension/manifests/
    build.py chrome       just that browser's extension

dist/emoji-prime-skill.zip                 the skill folder (unzips to emoji-prime/)
dist/youtube-emoji-prime-<browser>.zip     the extension, manifest.json at the zip root
dist/<browser>/                            the same, unpacked: what "Load unpacked" (Chrome) or
                                           "Load Temporary Add-on" (Firefox) takes

The zip names carry no version so .../releases/latest/download/<name> always works.
"""
import json, os, shutil, sys, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
EXT = os.path.join(HERE, "extension")
SKILL = os.path.join(HERE, "skill", "emoji-prime")
DIST = os.path.join(HERE, "dist")
SKIP = {"__pycache__", ".DS_Store"}


def zip_dir(src, zpath, prefix=""):
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for root, dirs, files in os.walk(src):
            dirs[:] = sorted(d for d in dirs if d not in SKIP)
            for f in sorted(files):
                if f not in SKIP:
                    p = os.path.join(root, f)
                    z.write(p, os.path.join(prefix, os.path.relpath(p, src)))
    print(f"  {zpath}")


def build_extension(browser):
    manifest = os.path.join(EXT, "manifests", f"{browser}.json")
    version = json.load(open(manifest, encoding="utf-8"))["version"]
    out = os.path.join(DIST, browser)
    shutil.rmtree(out, ignore_errors=True)
    shutil.copytree(os.path.join(EXT, "src"), out)
    shutil.copy(manifest, os.path.join(out, "manifest.json"))
    print(f"{browser} extension {version}: {out}")
    zip_dir(out, os.path.join(DIST, f"youtube-emoji-prime-{browser}.zip"))


def main():
    os.makedirs(DIST, exist_ok=True)
    browsers = sys.argv[1:]
    if not browsers:
        print("skill:")
        zip_dir(SKILL, os.path.join(DIST, "emoji-prime-skill.zip"), "emoji-prime")
        browsers = sorted(f[:-5] for f in os.listdir(os.path.join(EXT, "manifests")) if f.endswith(".json"))
    for b in browsers:
        build_extension(b)


if __name__ == "__main__":
    main()
