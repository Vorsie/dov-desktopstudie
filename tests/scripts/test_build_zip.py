"""De plugin-zip: alleen het pakket, zonder compilaten, onder één map `desktopstudie/`, met de
versie uit metadata.txt in de naam - want dat is wat QGIS's "Installeren uit ZIP" verwacht."""
from __future__ import annotations

import zipfile

from scripts import build_zip
from tests.versions import pyproject_version


def test_the_zip_holds_the_package_the_licence_and_nothing_compiled(tmp_path):
    """Het pakket met metadata.txt, icoon en noordpijl - en LICENSE en README.md erbij, want
    plugins.qgis.org weigert een zip zonder licentie - onder één map, zonder compilaten."""
    target = build_zip.build(dist=tmp_path)

    assert target.name == f"desktopstudie-{build_zip.version()}.zip"
    assert build_zip.version() == pyproject_version()
    with zipfile.ZipFile(target) as archive:
        names = archive.namelist()
    assert names and all(name.startswith("desktopstudie/") for name in names)
    for needed in ("desktopstudie/metadata.txt", "desktopstudie/__init__.py", "desktopstudie/qgis/plugin.py",
                   "desktopstudie/qgis/dialog.py", "desktopstudie/core/catalogue.py",
                   "desktopstudie/resources/icoon.svg", "desktopstudie/resources/noordpijl.svg",
                   "desktopstudie/LICENSE", "desktopstudie/README.md"):
        assert needed in names, needed
    assert not any("__pycache__" in name or name.endswith(".pyc") for name in names)
    assert not any("/tests/" in name for name in names)


def test_wanted_skips_caches_and_compiled_files():
    from pathlib import Path

    assert build_zip.wanted(Path("qgis/plugin.py"))
    assert not build_zip.wanted(Path("qgis/__pycache__/plugin.cpython-312.pyc"))
    assert not build_zip.wanted(Path("qgis/plugin.pyc"))
    assert not build_zip.wanted(Path("tests/test_x.py"))
