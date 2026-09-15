"""Small shims so the shell runs on QGIS 3.34 (PyQt5) through 4.x (PyQt6).

Everything the shell places on a layout is measured in millimetres, so the layout unit is
resolved once, here, in its scoped form (`Qgis.LayoutUnit.Millimeters` exists in 3.34 and is
the only spelling Qt6 accepts; the unscoped `QgsUnitTypes.LayoutMillimeters` is deprecated).

The other two shims here are about the environment rather than the API: naming an enum value
that PyQt5 hands over as a bare integer, and pointing the offscreen platform at a font
directory before it draws its first letter.
"""
from __future__ import annotations

import os
import sys
from typing import Optional

from qgis.core import Qgis, QgsLayoutPoint, QgsLayoutSize

MM = Qgis.LayoutUnit.Millimeters
OFFSCREEN = "offscreen"
FONT_DIR_VARIABLE = "QT_QPA_FONTDIR"
PLATFORM_VARIABLE = "QT_QPA_PLATFORM"
# Where a system keeps the fonts Qt's own database can read. Windows first: that is where the
# house face (Arial) lives, and the Linux path is the one the CI images carry.
FONT_DIRS = {"win32": r"C:\Windows\Fonts"}
DEFAULT_FONT_DIR = "/usr/share/fonts"


def point_mm(x: float, y: float) -> QgsLayoutPoint:
    """A layout position in millimetres."""
    return QgsLayoutPoint(x, y, MM)


def size_mm(width: float, height: float) -> QgsLayoutSize:
    """A layout size in millimetres."""
    return QgsLayoutSize(width, height, MM)


def qgis_version() -> str:
    """The running QGIS version, e.g. "3.40.15-Bratislava"."""
    return Qgis.QGIS_VERSION


def enum_name(holder, value) -> str:
    """The name QGIS gives an enum value, e.g. "LayerTypeWrong" or "FileError".

    A bare "3" in a log line or an exception tells nobody what went wrong. Where the name lives
    depends on the vintage: the enums QGIS has already modernised (`QgsZonalStatistics.Result`)
    arrive as real Python enums that carry `.name`, while an old unscoped C++ enum
    (`QgsLayoutExporter.ExportResult` on 3.40 / PyQt5) is a `sip.enumtype` whose members are
    plain integers listed on the OWNING CLASS, not on the enum type - `dir()` of that type is
    empty. So pass the class for those, the enum type for the modern ones, and either way the
    matching member is found (or the number, when it is not a member at all).
    """
    name = getattr(value, "name", None)
    if name:
        return str(name)
    for candidate in dir(holder):
        if not candidate.startswith("_") and getattr(holder, candidate, None) == value:
            return candidate
    return str(value)


def ensure_font_dir(log=None) -> Optional[str]:
    """Point the offscreen platform at a font directory, and say so. Returns the directory in use.

    The `offscreen` QPA plugin does not use the system font database; it reads the directory in
    QT_QPA_FONTDIR and otherwise looks inside the QGIS install, where no such directory exists
    ("QFontDatabase: Cannot find font directory"). Every letter then renders as a black box while
    the export still reports Success - the layout is right, only the typeface is missing. So the
    variable is set before the first render rather than left to whoever started the process.

    A caller who set it themselves is left alone, and on a real platform there is nothing to do.
    """
    if os.environ.get(PLATFORM_VARIABLE, "") != OFFSCREEN:
        return None
    existing = os.environ.get(FONT_DIR_VARIABLE)
    if existing:
        return existing
    chosen = FONT_DIRS.get(sys.platform, DEFAULT_FONT_DIR)
    if not os.path.isdir(chosen):
        if log:
            log.warning(f"Geen lettertypemap gevonden ({chosen}); offscreen tekent mogelijk zwarte blokjes")
        return None
    os.environ[FONT_DIR_VARIABLE] = chosen
    if log:
        log.info(f"{FONT_DIR_VARIABLE} stond leeg onder offscreen; gezet op {chosen}")
    return chosen
