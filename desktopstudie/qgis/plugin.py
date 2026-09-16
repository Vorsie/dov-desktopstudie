"""The plugin as QGIS loads it: one toolbar action, one menu entry, one dialog, one runner.

The plugin works in the project the user has open (decision 2026-09-15): the study's groups go
into `QgsProject.instance()`, the report layout into that project's layout manager, and the
standalone `studie.qgz` is written next to the PDF. No new project, no confirmation prompt.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction

from .task import PLUGIN_NAME, StudyRunner

MENU_NAME = "&DOV Desktopstudie"
ICON = Path(__file__).resolve().parents[1] / "resources" / "icoon.svg"


class DesktopstudiePlugin:
    def __init__(self, iface):
        self.iface = iface
        self.action: Optional[QAction] = None
        self.dialog = None
        self.runner: Optional[StudyRunner] = None

    def initGui(self) -> None:  # noqa: N802 - name required by QGIS
        self.action = QAction(QIcon(str(ICON)), PLUGIN_NAME, self.iface.mainWindow())
        self.action.setStatusTip("Geotechnische desktopstudie uit open data van DOV en geopunt")
        self.action.triggered.connect(self.run)
        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToMenu(MENU_NAME, self.action)

    def unload(self) -> None:
        if self.runner is not None and self.runner.running:
            self.runner.cancel()  # a study must not keep running into an unloaded plugin
        if self.action is not None:
            self.iface.removePluginMenu(MENU_NAME, self.action)
            self.iface.removeToolBarIcon(self.action)
            self.action = None
        if self.dialog is not None:
            self.dialog.close()
            self.dialog.deleteLater()
            self.dialog = None

    def run(self) -> None:
        """Show the dialog, non-modal: the user draws on the canvas while it stays open."""
        if self.dialog is None:
            from .dialog import StudyDialog  # widgets only when the user asks for them

            self.runner = StudyRunner(self.iface)
            self.dialog = StudyDialog(self.iface, self.runner, parent=self.iface.mainWindow())
        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()
