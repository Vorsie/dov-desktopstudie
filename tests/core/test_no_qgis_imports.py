"""De kern mag nooit qgis of PyQt importeren (huisregel)."""
from __future__ import annotations

import re
from pathlib import Path

CORE = Path(__file__).resolve().parents[2] / "desktopstudie" / "core"
FORBIDDEN = re.compile(r"^\s*(from|import)\s+(qgis|PyQt5|PyQt6|osgeo)\b", re.MULTILINE)


def test_core_has_no_qgis_or_qt_imports():
    offenders = []
    for path in CORE.rglob("*.py"):
        if FORBIDDEN.search(path.read_text(encoding="utf-8")):
            offenders.append(str(path.relative_to(CORE)))
    assert offenders == []


def test_package_import_does_not_need_qgis():
    import desktopstudie  # noqa: F401  (must not raise even without qgis installed)
    import desktopstudie.core  # noqa: F401
