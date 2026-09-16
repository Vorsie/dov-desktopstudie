"""Zip the plugin for installation from a ZIP: `dist/desktopstudie-<version>.zip`.

Only what QGIS needs goes in: the package with its resources and metadata.txt, without
`__pycache__` and compiled files, plus LICENSE and README.md from the repository root inside the
package folder - plugins.qgis.org refuses a zip without a licence. The tests live outside the
package, so a `tests` folder is skipped only as a safeguard. The version is read from metadata.txt,
the one place the plugin declares it.

  python scripts/build_zip.py            -> dist/desktopstudie-0.1.0.zip
  python scripts/build_zip.py --out map  -> map/desktopstudie-0.1.0.zip
"""
from __future__ import annotations

import argparse
import configparser
import sys
import zipfile
from pathlib import Path
from typing import List, Sequence

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "desktopstudie"
DIST = ROOT / "dist"
METADATA = "metadata.txt"
SKIP_DIRS = {"__pycache__", "tests"}
SKIP_SUFFIXES = {".pyc", ".pyo"}
EXTRA_FILES = ("LICENSE", "README.md")  # from the repository root, next to the package


def version(package: Path = PACKAGE) -> str:
    config = configparser.ConfigParser()
    config.read(package / METADATA, encoding="utf-8")
    return config["general"]["version"]


def wanted(relative: Path) -> bool:
    return not (set(relative.parts) & SKIP_DIRS) and relative.suffix not in SKIP_SUFFIXES


def members(package: Path = PACKAGE) -> List[Path]:
    """The files that go in, relative to the package, in a fixed order so two builds match."""
    return sorted(path.relative_to(package) for path in package.rglob("*")
                  if path.is_file() and wanted(path.relative_to(package)))


def build(package: Path = PACKAGE, dist: Path = DIST, extras: Sequence[str] = EXTRA_FILES) -> Path:
    dist.mkdir(parents=True, exist_ok=True)
    target = dist / f"{package.name}-{version(package)}.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for relative in members(package):
            archive.write(package / relative, f"{package.name}/{relative.as_posix()}")
        for name in extras:
            archive.write(package.parent / name, f"{package.name}/{name}")
    return target


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Zip de plugin voor installatie vanuit een ZIP.")
    parser.add_argument("--out", default=str(DIST), help="map voor de zip (standaard dist/)")
    args = parser.parse_args(argv)
    target = build(PACKAGE, Path(args.out))
    print(f"{target} ({len(members()) + len(EXTRA_FILES)} bestanden)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
