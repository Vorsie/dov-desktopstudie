"""DOV Desktopstudie - QGIS-plugin. QGIS-entry with a lazy import so the core stays importable."""
from __future__ import annotations


def classFactory(iface):  # noqa: N802 - name required by QGIS
    from .qgis.plugin import DesktopstudiePlugin

    return DesktopstudiePlugin(iface)
