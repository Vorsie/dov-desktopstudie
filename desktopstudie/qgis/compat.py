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
from qgis.PyQt.QtGui import QFont

MM = Qgis.LayoutUnit.Millimeters
# Arial is the house face, but a report is also produced on the Linux CI images and on machines
# that do not have it. Naming the substitutes keeps the metrics predictable instead of leaving the
# choice to whatever fontconfig happens to pick first.
#
# It lives HERE because both writers need it and neither may import the other: the layout already
# imports `layers`, so `layers` cannot import the layout back. Asking for no font at all is not a
# neutral choice - offscreen, Qt then picked a face that draws "kb12d37w-B19" as "kb12d37-N- B19".
FONT_FAMILIES = ["Arial", "Liberation Sans", "DejaVu Sans"]
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


def drop_colliding_labels(settings) -> None:
    """Leave a label out rather than draw it over one already placed.

    The knob moved: QGIS 3.32 introduced `QgsPalLayerSettings.placementSettings()` carrying
    `setOverlapHandling`, and that is the only spelling 4.x has. On 3.34 through 4.x it is there;
    on anything older it is not, and there the labelling engine's own default already drops what
    does not fit, so nothing is lost and nothing is pretended.

    Never read label settings BACK off a layer to check this (or the text buffer, or anything
    else): `QgsVectorLayerSimpleLabeling.settings()` hands out an object that does not survive the
    call. On 3.34 dereferencing it segfaults the process; on 4.x it answers with defaults, so it
    will cheerfully tell you a halo is absent while the map draws one. Measure the rendered image
    instead - `tests/qgis/test_layers.py::_halo_pixels` does exactly that.
    """
    handling = getattr(Qgis, "LabelOverlapHandling", None)
    placement = getattr(settings, "placementSettings", None)
    if handling is not None and placement is not None:
        placement().setOverlapHandling(handling.PreventOverlap)


def house_font(size: float, bold: bool = False) -> QFont:
    """The house face at this size, with the fallbacks that keep a Linux render readable."""
    font = QFont(FONT_FAMILIES[0], int(size))
    if hasattr(font, "setFamilies"):  # Qt >= 5.13, so every supported QGIS - but cheap to ask
        font.setFamilies(FONT_FAMILIES)
    font.setBold(bold)
    return font


def enum_name(holder, value) -> str:
    """The name QGIS gives an enum value, e.g. "LayerTypeWrong" or "FileError".

    A bare "3" in a log line or an exception tells nobody what went wrong, and which spelling
    works depends on the vintage. The enums QGIS has already modernised arrive as real Python
    enums that carry `.name`. An old unscoped C++ enum (`QgsLayoutExporter.ExportResult` on 3.40,
    and `QgsZonalStatistics.Result` on 3.34) is a `sip.enumtype`: `getattr` on it works, but
    `dir()` lists only int's own methods, so the type itself cannot be walked. Its members DO sit
    on the class that owns it, and the type says which class that is (`__qualname__` is
    "QgsZonalStatistics.Result", `__module__` the module it came from) - so `holder` may be the
    owning class OR the enum type, and both find the name.

    QGIS 3.34 is exactly why this matters: there `QgsZonalStatistics.Result` is such a type, and
    without the detour the log panel reads "DHMV zonale statistiek gaf 1".

    One class carries several enums and their numbers overlap (`QgsZonalStatistics.Count` is 1 and
    so is `Result.LayerTypeWrong`), so a member of the SAME enum type wins. A member that merely
    holds the same number counts only when it is the ONLY one: a name from the wrong enum lies,
    and the bare number it falls back to merely fails to inform.
    """
    name = getattr(value, "name", None)
    if name:
        return str(name)
    for owner in _enum_owners(holder):
        found = _member_named(owner, value)
        if found is not None:
            return found
    return str(value)


def _enum_owners(holder):
    """`holder`, and after it the class that owns it when `holder` is an enum type nested in one."""
    yield holder
    qualname = getattr(holder, "__qualname__", "")
    module = sys.modules.get(getattr(holder, "__module__", "") or "")
    if "." not in qualname or module is None:
        return
    owner = getattr(module, qualname.split(".")[0], None)
    if owner is not None and owner is not holder:
        yield owner


def _member_named(owner, value) -> Optional[str]:
    """The attribute of `owner` that IS `value`, preferring one of the same enum type.

    Same type is certain. Merely equal is a guess, and a guess is only worth printing when there
    is exactly one - two enums of one class that both own the number say nothing.
    """
    same_number = []
    for candidate in dir(owner):
        if candidate.startswith("_"):
            continue
        member = getattr(owner, candidate, None)
        if member != value:
            continue
        if type(member) is type(value):
            return candidate
        same_number.append(candidate)
    return same_number[0] if len(same_number) == 1 else None


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
