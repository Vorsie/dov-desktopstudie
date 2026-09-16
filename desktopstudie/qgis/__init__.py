"""QGIS shell: layers, DEM, layout, export, pipeline and the plugin UI.

Thin by design: no study logic lives here. `desktopstudie.core` never imports this package,
so the core stays testable in a plain Python (see tests/core/test_no_qgis_imports.py).
Note for readers: this package is named `qgis` but absolute imports win inside it, so
`from qgis.core import ...` below reaches QGIS itself, never this package.
"""
from __future__ import annotations
