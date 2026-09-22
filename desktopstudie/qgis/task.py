"""The study as the plugin runs it: a QgsTask for the two network halves, a runner on the main
thread for the rest, and the log that lands in the QGIS log panel.

Three rules keep the GUI alive while a study of a few minutes runs.

*Nothing in the worker touches a widget or the project.* `StudyTask.run` does `run_core` and
`prepare`, which between them are the core and the whole of `prefetch` - the import graph says so,
and that is where to check it rather than here. Progress goes out through a signal that Qt queues
to the main thread, and what comes back is plain Python: a result, a `Prepared`, or an exception.

*The main thread yields.* `finish` polls `should_cancel` between phases, between pages of the
layout and between runs of the exporter, and the runner's `should_cancel` pumps the event loop
before it answers - so the progress bar moves and the Cancel button is heard, and a cancel stops
the run at the next of those points, seconds at most.

*The task is not the place for the main-thread half.* `QgsTask.finished()` runs inside the task
manager's slot and the manager deletes the task right after it, so the outcome leaves the task as
data and the runner schedules the assembly on itself with a zero timer. Nothing ever touches the
task again after `finished()`.
"""
from __future__ import annotations

import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from qgis.core import (
    Qgis,
    QgsApplication,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsMessageLog,
    QgsProject,
    QgsRectangle,
    QgsTask,
)
from qgis.PyQt import sip
from qgis.PyQt.QtCore import QCoreApplication, QObject, QTimer, QUrl, pyqtSignal
from qgis.PyQt.QtGui import QDesktopServices
from qgis.PyQt.QtWidgets import QProgressBar, QPushButton

from ..core import geometry
from ..core.geometry import CRS
from ..core.logging_util import Log
from ..core.model import StudyResult, StudyZone
from ..core.report_content import ReportMeta
from ..core.study import Settings, StudyCancelled
from . import pipeline
from .pipeline import CORE_SHARE, PipelineResult, Prepared, part_of

PLUGIN_NAME = "DOV Desktopstudie"
LOG_TAB = PLUGIN_NAME
OPEN_PDF = "Open PDF"
CANCEL = "Annuleren"
ZOOM_MARGIN = 0.5  # of the zone's own size, on every side
MAX_NAMED_SOURCES = 8
_LEVELS = {"WARNING": Qgis.MessageLevel.Warning, "ERROR": Qgis.MessageLevel.Critical}


def message_log_sink(line: str) -> None:
    """One log line into the QGIS log panel, under the plugin's tab, at the level its prefix
    names ("[qgis WARNING module] ..."). Safe from any thread: QgsMessageLog only emits a signal."""
    parts = line.split(" ", 2)
    level = _LEVELS.get(parts[1], Qgis.MessageLevel.Info) if len(parts) > 1 else Qgis.MessageLevel.Info
    QgsMessageLog.logMessage(line, LOG_TAB, level)


def plugin_log(module: str = "plugin") -> Log:
    """The plugin's logger: INFO and up into the log panel; DEBUG stays out unless asked for."""
    return Log(module, message_log_sink, scope="qgis")


@dataclass
class StudyRequest:
    """Everything the dialog decided, as data: what to study, how, and where to write it."""
    zone: StudyZone
    settings: Settings
    meta: ReportMeta
    out_dir: Path
    cache_mode: str
    legends: bool
    # The disk cache, shared by every run under the same output folder: a run folder is fresh
    # every time, and a cache inside it would never be hit twice.
    cache_dir: Optional[Path] = None


@dataclass
class WorkerOutcome:
    """What the worker hands the main thread: a result with its prefetches, or why not."""
    result: Optional[StudyResult]
    prepared: Optional[Prepared]
    error: Optional[BaseException]
    cancelled: bool


class StudyTask(QgsTask):
    """The worker half of one study; see the module docstring for what may run here."""

    progressed = pyqtSignal(float, str)  # fraction of the whole study, phase name

    def __init__(self, request: StudyRequest, log: Log,
                 on_finished: Callable[[WorkerOutcome], None]):
        super().__init__(f"{PLUGIN_NAME}: {request.meta.project}", QgsTask.Flag.CanCancel)
        self.request, self.log, self.on_finished = request, log, on_finished
        self.result: Optional[StudyResult] = None
        self.prepared: Optional[Prepared] = None
        self.error: Optional[BaseException] = None
        self.cancelled = False

    def run(self) -> bool:  # worker thread
        request = self.request
        try:
            # One client for both halves: one disk cache, so the legends phase re-uses what the
            # core already fetched and a re-run costs nothing.
            client = pipeline.make_client(request.out_dir, self.log, request.cache_mode, request.cache_dir)
            self.result = pipeline.run_core(request.zone, request.settings, request.out_dir, self.log,
                                            progress=part_of(self._progress, 0.0, CORE_SHARE),
                                            should_cancel=self.isCanceled,
                                            cache_mode=request.cache_mode, client=client)
            self.prepared = pipeline.prepare(self.result, request.meta, request.out_dir, self.log,
                                             progress=part_of(self._progress, CORE_SHARE, 1.0),
                                             should_cancel=self.isCanceled, client=client,
                                             cache_mode=request.cache_mode, legends=request.legends)
            return True
        except StudyCancelled:
            self.cancelled = True
            self.log.info("studie afgebroken in de werkthread")
            return False
        except Exception as exc:  # noqa: BLE001 - every failure is reported, on the main thread
            self.error = exc
            self.log.error(f"studie mislukt in de werkthread: {type(exc).__name__}: {exc}")
            self.log.debug(traceback.format_exc())
            return False

    def _progress(self, fraction: float, message: str) -> None:
        self.setProgress(fraction * 100.0)
        self.progressed.emit(fraction, message)

    def finished(self, ok: bool) -> None:  # main thread, called by the task manager
        # A task cancelled before it ever ran comes here with ok=False and no exception.
        cancelled = self.cancelled or (not ok and self.error is None)
        outcome = WorkerOutcome(self.result if ok else None, self.prepared if ok else None,
                                self.error, cancelled)
        # The task outlives this call (the manager deletes it later, at its own pace) and must
        # not keep its caller alive that long: the callback and the connections go here.
        callback, self.on_finished = self.on_finished, None
        try:
            self.progressed.disconnect()
        except TypeError:  # nothing was connected
            pass
        try:
            callback(outcome)
        except Exception as exc:  # noqa: BLE001 - an exception here would vanish inside Qt
            self.log.error(f"afhandeling van de uitkomst mislukt: {type(exc).__name__}: {exc}")
            self.log.debug(traceback.format_exc())


class StudyRunner(QObject):
    """One study from Start to the message that says where the report is.

    Owns the progress item in the message bar (with its Cancel button), starts the task, and runs
    `finish` on the main thread once the worker is done. `finished` carries the `PipelineResult`,
    or None when the study failed or was stopped; the dialog re-enables its Start button on it.
    """

    finished = pyqtSignal(object)

    def __init__(self, iface, log: Optional[Log] = None, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.iface = iface
        self.log = log or plugin_log("runner")
        self._request: Optional[StudyRequest] = None
        self._task: Optional[StudyTask] = None
        self._outcome: Optional[WorkerOutcome] = None
        self._cancelled = False
        self._item = None
        self._progress_bar: Optional[QProgressBar] = None
        self._message = ""
        # The user may close the progress message; QGIS deletes it, and the run carries on
        # without a bar rather than on a dead widget.
        self.iface.messageBar().widgetRemoved.connect(self._progress_item_removed)

    def shutdown(self) -> None:
        """Let go of the message bar. The bar belongs to QGIS and outlives the plugin, so a
        connection left behind calls a slot of an unloaded plugin - which is what Plugin Reloader
        does every time it reloads. Safe to call twice: a connection that is already gone is not
        an error here, it is the goal."""
        try:
            self.iface.messageBar().widgetRemoved.disconnect(self._progress_item_removed)
        except (TypeError, RuntimeError) as exc:  # not connected, or the bar itself is gone
            self.log.debug(f"berichtenbalk al losgemaakt: {type(exc).__name__}")

    @property
    def running(self) -> bool:
        return self._request is not None

    @property
    def request(self) -> Optional[StudyRequest]:
        """The study under way, None between studies."""
        return self._request

    @property
    def progress_message(self) -> str:
        """The phase the progress item last showed."""
        return self._message

    def start(self, request: StudyRequest) -> None:
        if self.running:
            raise RuntimeError("er loopt al een studie; wacht tot ze klaar is of breek ze af")
        self._request, self._cancelled, self._outcome = request, False, None
        self.log.info(f"Studie gestart: {request.meta.project}; zone {request.zone.name}; "
                      f"uitvoer {request.out_dir}")
        self._show_progress_item()
        task = StudyTask(request, self.log.child("taak"), self._worker_done)
        task.progressed.connect(self._show_progress)
        self._task = task
        QgsApplication.taskManager().addTask(task)

    def cancel(self) -> None:
        """Stop at the next point the run looks: the worker's flag, or the main thread's."""
        self._cancelled = True
        if self._task is not None:
            self._task.cancel()
        self._show_progress(None, "Afbreken...")

    # --- the seam between the two threads ---------------------------------------------------------

    def _should_cancel(self) -> bool:
        """Polled by `finish` on the main thread: the moment the GUI gets to breathe."""
        QCoreApplication.processEvents()
        return self._cancelled

    def _worker_done(self, outcome: WorkerOutcome) -> None:
        self._task = None  # the task manager deletes it after this call; never touch it again
        self._outcome = outcome
        QTimer.singleShot(0, self._assemble)

    def _assemble(self) -> None:
        """The main-thread half, in a timer slot: whatever happens, `finished` fires at the end,
        because the dialog's Start button waits on it.

        A failure here can land AFTER the report is on disk - the zoom or the message bar itself -
        and then the log panel is the only place that says so. Nobody opens that panel unprompted,
        so the failure also goes to the message bar: a study that ends in silence reads as a study
        that never ran.
        """
        request, outcome = self._request, self._outcome
        result: Optional[PipelineResult] = None
        try:
            self._freeze_canvas(True)
            try:
                result = self._finish(request, outcome)
            finally:
                self._freeze_canvas(False)
                self._hide_progress_item()
                self._request, self._outcome = None, None
            if result is not None:
                self._delivered(result)
        except Exception as exc:  # noqa: BLE001 - a slot must not raise, and the study itself is done
            self.log.error(f"afronding van de studie mislukt: {type(exc).__name__}: {exc}")
            self.log.debug(traceback.format_exc())
            self._push_safely(Qgis.MessageLevel.Critical,
                              f"Afronding van de studie mislukt: {type(exc).__name__}: {exc}")
        finally:
            self.finished.emit(result)

    def _push_safely(self, level, text: str) -> None:
        """The last message of a run, on a bar that may itself be what broke. A message that
        cannot be shown is logged; raising here would cost the `finished` signal."""
        try:
            self._push(level, text)
        except Exception as exc:  # noqa: BLE001 - there is nowhere left to report this to
            self.log.error(f"melding niet getoond: {type(exc).__name__}: {exc}")

    def _freeze_canvas(self, frozen: bool) -> None:
        """No render while the study fills the project: every layer that lands in the open project
        would otherwise start one, and a WMS render pulls tiles on the main thread. One refresh at
        the end instead. A canvas that cannot be reached is logged, not fatal."""
        try:
            canvas = self.iface.mapCanvas()
            canvas.freeze(frozen)
            if not frozen:
                canvas.refresh()
        except Exception as exc:  # noqa: BLE001 - the study does not depend on the canvas
            self.log.warning(f"canvas niet {'bevroren' if frozen else 'vrijgegeven'}: {exc}")

    def _finish(self, request: StudyRequest, outcome: WorkerOutcome) -> Optional[PipelineResult]:
        if outcome.cancelled or self._cancelled:
            return self._stopped()
        if outcome.error is not None:
            return self._failed(outcome.error)
        try:
            return pipeline.finish(QgsProject.instance(), outcome.result, request.meta, request.out_dir,
                                   self.log, progress=part_of(self._show_progress, CORE_SHARE, 1.0),
                                   legends=request.legends, should_cancel=self._should_cancel,
                                   cache_mode=request.cache_mode, prepared=outcome.prepared,
                                   compact=request.settings.compact)
        except StudyCancelled:
            return self._stopped()
        except Exception as exc:  # noqa: BLE001 - reported to the user, never swallowed
            self.log.debug(traceback.format_exc())
            return self._failed(exc)

    # --- what the user sees -----------------------------------------------------------------------

    def _stopped(self) -> None:
        self.log.info("Studie afgebroken door de gebruiker")
        self._push(Qgis.MessageLevel.Warning, "Studie afgebroken.")
        return None

    def _failed(self, error: BaseException) -> None:
        self.log.error(f"Studie mislukt: {type(error).__name__}: {error}")
        self._push(Qgis.MessageLevel.Critical, f"Studie mislukt: {error}")
        return None

    def _delivered(self, out: PipelineResult) -> None:
        self._zoom_to(out.result.zone)
        if out.pdf is not None:
            self._push_report(out.pdf)
        else:
            self._push(Qgis.MessageLevel.Warning, "Rapport niet gemaakt: " + "; ".join(out.failures))
        if out.failures and out.pdf is not None:
            self._push(Qgis.MessageLevel.Warning, "Mislukte producten: " + "; ".join(out.failures))
        failed = [p.source for p in out.result.provenance if not p.ok]
        if failed:
            named = ", ".join(failed[:MAX_NAMED_SOURCES]) + (" ..." if len(failed) > MAX_NAMED_SOURCES else "")
            self._push(Qgis.MessageLevel.Warning,
                       f"{len(failed)} bron(nen) antwoordden niet (zie hoofdstuk Bronnen): {named}")

    def _zoom_to(self, zone: StudyZone) -> None:
        canvas = self.iface.mapCanvas()
        minx, miny, maxx, maxy = zone.bbox
        margin = max(maxx - minx, maxy - miny) * ZOOM_MARGIN
        extent = QgsRectangle(*geometry.expand_bbox(zone.bbox, margin))
        lambert = QgsCoordinateReferenceSystem(CRS)
        target = canvas.mapSettings().destinationCrs()
        if target.isValid() and target != lambert:
            extent = QgsCoordinateTransform(lambert, target, QgsProject.instance()).transformBoundingBox(extent)
        canvas.setExtent(extent)
        canvas.refresh()

    def _push(self, level, text: str) -> None:
        self.iface.messageBar().pushMessage(PLUGIN_NAME, text, level, 0)

    def _push_report(self, pdf: Path) -> None:
        bar = self.iface.messageBar()
        item = bar.createMessage(PLUGIN_NAME, f"Rapport: {pdf}")
        button = QPushButton(OPEN_PDF)
        button.clicked.connect(lambda _checked=False, path=pdf: QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))))
        item.layout().addWidget(button)
        bar.pushWidget(item, Qgis.MessageLevel.Success, 0)

    def _progress_item_removed(self, widget) -> None:
        """Our progress item left the bar - the user closed it, or we popped it. Forget it either
        way: QGIS deletes the item after this signal, and any later call on it would raise."""
        item = self._item
        if item is None:
            return
        if sip.isdeleted(item) or sip.unwrapinstance(widget) == sip.unwrapinstance(item):
            self._item, self._progress_bar = None, None
            if self.running:
                self.log.info("voortgangsbericht weggeklikt; de studie loopt door, zie het logpaneel")

    def _show_progress_item(self) -> None:
        bar = self.iface.messageBar()
        self._item = bar.createMessage(PLUGIN_NAME, "Studie gestart")
        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        cancel = QPushButton(CANCEL)
        cancel.clicked.connect(self.cancel)
        self._item.layout().addWidget(self._progress_bar)
        self._item.layout().addWidget(cancel)
        bar.pushWidget(self._item, Qgis.MessageLevel.Info, 0)

    def _show_progress(self, fraction: Optional[float], message: str) -> None:
        self._message = message
        if self._item is None:
            return
        if sip.isdeleted(self._item):
            self._item, self._progress_bar = None, None
            return
        if fraction is not None and self._progress_bar is not None:
            self._progress_bar.setValue(int(round(fraction * 100.0)))
        self._item.setText(message)

    def _hide_progress_item(self) -> None:
        item = self._item
        self._item, self._progress_bar = None, None
        if item is not None and not sip.isdeleted(item):
            self.iface.messageBar().popWidget(item)
