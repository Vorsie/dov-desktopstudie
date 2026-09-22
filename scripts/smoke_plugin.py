"""Drive the plugin inside a real QGIS, unattended: enable it, open the dialog, fill the address
mode, start the study, wait for it, write a status file and quit.

  "C:\\Program Files\\QGIS 3.40.15\\bin\\qgis-ltr-bin.exe"
      --profile smoke --nologo --noversioncheck --code scripts\\smoke_plugin.py

A profile of its own (`--profile smoke`): the run enables the plugin and saves settings (bedrijf,
auteur, uitvoermap) in whatever profile it runs in, and the developer's own profile is not the
place for that. The junction has to exist in that profile (`scripts/dev_link.cmd smoke`).
Everything here is event-driven (QTimer): under
`--code` the script runs before the event loop, so it may only schedule work. The status lands in
uitvoer/plugin_gent/smoke_status.json, a log next to it; both are what a reader checks afterwards,
because the QGIS window closes itself at the end.

Two environment variables, both optional:

  DESKTOPSTUDIE_FRAMES   folder to capture the window into while the study runs (one PNG per
                         frame; `scripts/demo_gif.py` turns them into the README demo). Unset:
                         capture nothing, which is how the smoke run normally goes.
  DESKTOPSTUDIE_PROJECT  the study name (default "Smoke Gent").

The frames come from `QWidget.grab()`, not from a screenshot: that yields the window itself,
without whatever happens to sit on top of it. The dialog is a window of its own and is therefore
not in that grab; it is painted onto the frame at its own offset, with a thin border so it still
reads as a separate window.
"""
from __future__ import annotations

import json
import os
import sys
import time
import traceback
from pathlib import Path

from qgis.core import QgsApplication, QgsProject, QgsSettings
from qgis.PyQt.QtCore import QPoint, QTimer
from qgis.PyQt.QtGui import QColor, QPainter
from qgis.utils import active_plugins, iface, loadPlugin, plugins, startPlugin

PLUGIN = "desktopstudie"
ADDRESS = "Kortrijksesteenweg 100 Gent"
BUFFER_M = 50.0
POLL_MS = 500
GEOCODE_TIMEOUT_S = 60.0
STUDY_TIMEOUT_S = 40 * 60.0
QUIT_DELAY_MS = 1500
PROJECT = os.environ.get("DESKTOPSTUDIE_PROJECT") or "Smoke Gent"
FRAMES = Path(os.environ["DESKTOPSTUDIE_FRAMES"]) if os.environ.get("DESKTOPSTUDIE_FRAMES") else None
FRAME_MS = 1500          # one frame per second and a half: enough to see a phase begin
FRAME_MAX = 400          # a brake, so a wedged run does not leave a folder full of frames
FRAME_WINDOW = (1600, 1000)
FRAME_QUIT_MS = 9000     # while capturing the window stays open longer: the canvas still draws


def _root() -> Path:
    """The checkout: `__file__` is not set under --code, but the path is on the command line.
    QGIS keeps its own arguments (`QgsApplication.arguments()`) and hands Python a bare
    `sys.argv`, so the command line is read from the application, `sys.argv` as a fallback.
    (Same helper in zip_check.py: a --code script cannot import a sibling before it knows where
    the checkout is.)"""
    for argv in (list(QgsApplication.arguments()), sys.argv):
        if "--code" in argv:
            return Path(argv[argv.index("--code") + 1]).resolve().parents[1]
    return Path.cwd()


ROOT = _root()
OUT = ROOT / "uitvoer" / "plugin_gent"
STATUS = OUT / "smoke_status.json"
LOG = OUT / "smoke_log.txt"
T0 = time.monotonic()
state = {"done": False, "frames": 0}


def note(message: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    line = f"{time.monotonic() - T0:7.1f} s  {message}"
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
    print(line)


def write_status(**fields) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    fields.setdefault("seconds", round(time.monotonic() - T0, 1))
    STATUS.write_text(json.dumps(fields, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def grab(tag: str) -> None:
    """One frame of the main window, with the dialog drawn on top where it stands."""
    if FRAMES is None or state["frames"] >= FRAME_MAX:
        return
    window = iface.mainWindow()
    shot = window.grab()
    dialog = getattr(plugins.get(PLUGIN), "dialog", None)
    if dialog is not None and dialog.isVisible():
        offset = dialog.mapToGlobal(QPoint(0, 0)) - window.mapToGlobal(QPoint(0, 0))
        painter = QPainter(shot)
        painter.drawPixmap(offset, dialog.grab())
        painter.setPen(QColor(90, 90, 90))
        painter.drawRect(offset.x() - 1, offset.y() - 1, dialog.width() + 1, dialog.height() + 1)
        painter.end()
    state["frames"] += 1
    FRAMES.mkdir(parents=True, exist_ok=True)
    shot.save(str(FRAMES / f"frame_{state['frames']:03d}_{tag}.png"))


def grab_loop() -> None:
    if FRAMES is None or state.get("no_frames"):
        return
    grab("loop")
    QTimer.singleShot(FRAME_MS, grab_loop)


def quit_qgis() -> None:
    QgsProject.instance().setDirty(False)  # no "save project?" prompt on the way out
    delay = FRAME_QUIT_MS if FRAMES is not None else QUIT_DELAY_MS
    QTimer.singleShot(delay - 500, lambda: state.__setitem__("no_frames", True))
    QTimer.singleShot(delay, iface.mainWindow().close)


def fail(message: str) -> None:
    if state["done"]:
        return
    state["done"] = True
    note("MISLUKT: " + message)
    write_status(ok=False, error=message)
    quit_qgis()


def wait_for(condition, timeout_s: float, then, what: str) -> None:
    """Poll `condition` on a timer until it holds, then call `then`; fail after `timeout_s`."""
    deadline = time.monotonic() + timeout_s

    def poll():
        try:
            if condition():
                then()
                return
        except Exception:  # noqa: BLE001 - reported in the status file
            fail(f"{what}: {traceback.format_exc()}")
            return
        if time.monotonic() > deadline:
            fail(f"{what}: niet binnen {timeout_s:.0f} s")
            return
        QTimer.singleShot(POLL_MS, poll)

    QTimer.singleShot(POLL_MS, poll)


def step_enable():
    if STATUS.exists():
        STATUS.unlink()
    # A profile that ran this before has the plugin enabled, and QGIS started it at launch;
    # startPlugin() then answers False for "already active", which is not a failure.
    if PLUGIN in active_plugins:
        note("plugin was al actief in dit profiel")
    elif not loadPlugin(PLUGIN):
        fail("plugin laden mislukt (staat de junction er? zie het logpaneel voor de importfout)")
        return
    elif not startPlugin(PLUGIN):
        fail("plugin starten mislukt (zie het logpaneel)")
        return
    else:
        note("plugin geladen en gestart")
    QgsSettings().setValue(f"PythonPlugins/{PLUGIN}", True)
    plugin = plugins[PLUGIN]
    plugin.run()
    dialog = plugin.dialog
    dialog.address_edit.setText(ADDRESS)
    dialog.buffer_spin.setValue(BUFFER_M)
    dialog.project_edit.setText(PROJECT)
    dialog.author_edit.setText("smoke_plugin.py")
    dialog.company_edit.setText("DOV Desktopstudie")
    dialog.output_edit.setText(str(OUT))
    dialog.legends_check.setChecked(True)
    if FRAMES is not None:
        window = iface.mainWindow()
        window.showNormal()  # a maximised window ignores resize()
        window.resize(*FRAME_WINDOW)
        dialog.move(window.x() + window.width() - dialog.width() - 60, window.y() + 140)
        grab("dialoog")
        QTimer.singleShot(FRAME_MS, grab_loop)
    dialog.search_address()
    note(f"adres gezocht: {ADDRESS}")
    wait_for(lambda: dialog.search_button.isEnabled(), GEOCODE_TIMEOUT_S, lambda: step_start(plugin, dialog),
             "geocoderen")


def step_start(plugin, dialog):
    if not dialog.hits:
        fail("geen adreskandidaat gevonden")
        return
    note(f"kandidaat: {dialog.hits[0].address}")
    runner = plugin.runner
    runner.finished.connect(lambda result: step_finished(runner, dialog, result))
    progress = {"last": ""}
    # How often the canvas starts a render while the study runs: every WMS layer added to the
    # open project can trigger one, and each of those pulls tiles on the main thread.
    iface.mapCanvas().renderStarting.connect(
        lambda: state.__setitem__("renders", state.get("renders", 0) + 1))

    def log_progress():
        if state["done"]:
            return
        text = runner.progress_message
        if text != progress["last"]:
            progress["last"] = text
            note(f"voortgang: {text} (canvas renders tot nu: {state.get('renders', 0)})")
        QTimer.singleShot(2000, log_progress)

    dialog.start()
    if not runner.running:
        fail("de studie is niet gestart (zie de berichtenbalk / het logpaneel)")
        return
    grab("start")
    note(f"studie gestart, uitvoer {runner.request.out_dir}")
    QTimer.singleShot(2000, log_progress)
    wait_for(lambda: state["done"], STUDY_TIMEOUT_S, lambda: None, "studie")


def step_finished(runner, dialog, result):
    if state["done"]:
        return
    state["done"] = True
    project = QgsProject.instance()
    groups = [group.name() for group in project.layerTreeRoot().findGroups()]
    layouts = [layout.name() for layout in project.layoutManager().printLayouts()]
    if result is None:
        note("studie eindigde zonder resultaat (mislukt of afgebroken)")
        write_status(ok=False, error="geen resultaat", groups=groups, layouts=layouts)
    else:
        failed = [p.source for p in result.result.provenance if not p.ok]
        pages = sum(len(chapter.pages) for chapter in result.report.chapters)
        note(f"klaar: pdf {result.pdf}, {pages} pagina's, mislukt {result.failures}, bronnen mislukt {failed}")
        write_status(ok=result.pdf is not None and not result.failures, pdf=result.pdf,
                     project_file=result.project_file, geopackage=result.geopackage, pages=pages,
                     failures=result.failures, failed_sources=failed, timings=result.timings,
                     groups=groups, layouts=layouts, start_enabled=dialog.start_button.isEnabled(),
                     canvas_renders=state.get("renders", 0), profile=QgsApplication.qgisSettingsDirPath())
    if FRAMES is not None:
        for group in project.layerTreeRoot().findGroups():
            if group.name().startswith("DOV Desktopstudie"):
                group.setExpanded(True)  # the study's layer tree open in the last frames, not collapsed
    quit_qgis()


try:
    note(f"smoke start in {ROOT}")
    QTimer.singleShot(POLL_MS, step_enable)
except Exception:  # noqa: BLE001 - the status file is the only channel out
    fail(traceback.format_exc())
