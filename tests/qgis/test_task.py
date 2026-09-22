"""De QgsTask van de plugin: de kern en de netwerkhelft in de werkthread, de uitkomst naar de
hoofdthread. Met een gestubde pijplijn - geen dienst, geen project - maar wel via de echte
taakbeheerder van QGIS, want dat de uitkomst op de hoofdthread aankomt is precies wat te bewijzen
valt."""
from __future__ import annotations

import threading
import time

from tests.qgis.conftest import FakeIface

TIMEOUT_S = 30.0


def _request(tmp_path):
    from desktopstudie.core import geometry
    from desktopstudie.core.model import StudyZone
    from desktopstudie.core.report_content import ReportMeta
    from desktopstudie.core.study import Settings
    from desktopstudie.qgis.task import StudyRequest

    zone = StudyZone(ring=geometry.buffer_point(104326.0, 192506.0, 50.0), name="Gent test", radius_m=500.0)
    return StudyRequest(zone, Settings(), ReportMeta(project="Test", author="A", company="B"),
                        tmp_path / "studies" / "run", "use", False, tmp_path / "studies" / "cache")


def _log(lines):
    from desktopstudie.core.logging_util import Log

    return Log("plugin", lines.append, scope="qgis")


def _wait_until(done):
    """Spin the event loop until `done()` - the task manager reports on the main thread through
    queued signals, and nothing arrives without a loop turning. Afterwards the deferred deletes
    are flushed too: a finished task the manager has not deleted yet would otherwise die with
    the application at the end of the session, where anything it still references dies with it."""
    from qgis.PyQt.QtCore import QCoreApplication, QEvent

    deadline = time.monotonic() + TIMEOUT_S
    while not done():
        QCoreApplication.processEvents()
        time.sleep(0.01)
        assert time.monotonic() < deadline, "de taak is niet binnen de tijd afgerond"
    for _round in range(5):
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        QCoreApplication.processEvents()


def _fake_result(zone):
    from desktopstudie.core.model import StudyResult

    return StudyResult(zone=zone, created_at="2026-09-16T10:00:00")


def _fake_prepared():
    from desktopstudie.qgis.pipeline import Prepared

    return Prepared({}, {}, set(), {}, set(), [], set(), [("Kaartbeelden", 0.1)])


def test_the_worker_runs_core_and_prepare_and_hands_the_outcome_to_the_main_thread(qgs_app, tmp_path,
                                                                                 monkeypatch):
    """Beide netwerkhelften draaien in de werkthread, met één HTTP-client (één schijfcache); de
    voortgang van de kern beslaat de eerste helft van de balk; en de callback krijgt resultaat én
    voorbereiding op de hoofdthread, zonder fout."""
    from qgis.core import QgsApplication

    from desktopstudie.qgis import pipeline
    from desktopstudie.qgis.task import StudyTask

    request = _request(tmp_path)
    result, prepared = _fake_result(request.zone), _fake_prepared()
    calls = []

    def fake_core(zone, settings, out_dir, log, progress=None, should_cancel=None, cache_mode="use",
                  client=None):
        calls.append(("core", threading.current_thread().name, client))
        progress(0.5, "halverwege de kern")
        return result

    def fake_prepare(res, meta, out_dir, log, progress=None, should_cancel=None, client=None,
                     cache_mode="use", legends=True):
        calls.append(("prepare", threading.current_thread().name, client))
        assert res is result and legends is False
        return prepared

    monkeypatch.setattr(pipeline, "run_core", fake_core)
    monkeypatch.setattr(pipeline, "prepare", fake_prepare)
    outcomes, phases = [], []
    task = StudyTask(request, _log([]), outcomes.append)
    task.progressed.connect(lambda fraction, message: phases.append((fraction, message)))

    QgsApplication.taskManager().addTask(task)
    _wait_until(lambda: outcomes)

    outcome = outcomes[0]
    assert outcome.result is result and outcome.prepared is prepared
    assert outcome.error is None and outcome.cancelled is False
    assert [name for name, _thread, _client in calls] == ["core", "prepare"]
    assert all(thread != threading.current_thread().name for _name, thread, _client in calls), calls
    assert calls[0][2] is calls[1][2] and calls[0][2] is not None, "één client voor beide helften"
    # The cache lives next to the run folders, not in one: a re-run of the same study with the
    # cache on must find what the previous run fetched.
    assert calls[0][2].cache_dir == request.cache_dir == tmp_path / "studies" / "cache"
    assert not request.cache_dir.is_relative_to(request.out_dir)
    assert (0.25, "halverwege de kern") in phases


def test_an_exception_in_the_worker_reaches_the_callback_as_the_error_and_the_log(qgs_app, tmp_path,
                                                                                 monkeypatch):
    """Een dienst die omvalt in de werkthread hoort als fout bij de callback aan te komen én in het
    logpaneel te staan - nooit stil, nooit als een "klaar" zonder rapport."""
    from qgis.core import QgsApplication

    from desktopstudie.qgis import pipeline
    from desktopstudie.qgis.task import StudyTask

    def broken(*args, **kwargs):
        raise RuntimeError("DOV WFS antwoordt niet")

    monkeypatch.setattr(pipeline, "run_core", broken)
    outcomes, lines = [], []
    task = StudyTask(_request(tmp_path), _log(lines), outcomes.append)

    QgsApplication.taskManager().addTask(task)
    _wait_until(lambda: outcomes)

    outcome = outcomes[0]
    assert outcome.result is None and outcome.prepared is None and outcome.cancelled is False
    assert isinstance(outcome.error, RuntimeError) and "DOV WFS antwoordt niet" in str(outcome.error)
    assert any("ERROR" in line and "DOV WFS antwoordt niet" in line for line in lines), lines


def test_a_cancelled_task_reports_cancelled_not_an_error(qgs_app, tmp_path, monkeypatch):
    """Annuleren loopt via de vlag van de taak: de pijplijn krijgt `isCanceled` als should_cancel,
    stopt met Cancelled, en de callback ziet "afgebroken" - geen fout, geen resultaat."""
    from qgis.core import QgsApplication

    from desktopstudie.core.parallel import Cancelled
    from desktopstudie.qgis import pipeline
    from desktopstudie.qgis.task import StudyTask

    seen = []

    def core_that_gets_cancelled(zone, settings, out_dir, log, progress=None, should_cancel=None,
                                 cache_mode="use", client=None):
        seen.append(should_cancel())
        task.cancel()
        seen.append(should_cancel())
        if should_cancel():
            raise Cancelled("afgebroken door de gebruiker")
        return _fake_result(zone)

    monkeypatch.setattr(pipeline, "run_core", core_that_gets_cancelled)
    outcomes = []
    task = StudyTask(_request(tmp_path), _log([]), outcomes.append)

    QgsApplication.taskManager().addTask(task)
    _wait_until(lambda: outcomes)

    assert seen == [False, True]
    outcome = outcomes[0]
    assert outcome.cancelled is True and outcome.error is None and outcome.result is None


def _log_signal():
    """Het signaal waarmee DEZE QGIS een logregel doorgeeft.

    QGIS 4 heeft `messageReceived(message, tag, level)` afgekeurd en zendt het niet meer uit:
    `QgsMessageLog::emitMessage` doet daar `emit messageReceivedWithFormat(message, tag, level,
    format)` plus `emit messageReceived(bool)` (qgsmessagelog.cpp op master). Een test die aan het
    oude signaal blijft hangen vangt daar niets meer - wat op 4.x als een leeg logpaneel LEEST
    terwijl de plugin niets mankeert: die schrijft met `QgsMessageLog.logMessage` en het logpaneel
    luistert in C++. Op 3.34/3.40 bestaat het nieuwe signaal niet (geverifieerd op 3.40.15).
    """
    from qgis.core import QgsApplication

    log = QgsApplication.messageLog()
    return getattr(log, "messageReceivedWithFormat", None) or log.messageReceived


def test_the_log_sink_sorts_lines_into_the_qgis_message_log_by_level(qgs_app):
    """Elke logregel van de plugin landt in het logpaneel onder het tabblad "DOV Desktopstudie",
    met het niveau uit het voorvoegsel: een WARNING wordt geel, een ERROR rood."""
    from qgis.core import Qgis

    from desktopstudie.qgis.task import LOG_TAB, plugin_log

    received = []

    def record(message, tag, level, *_format):  # 4.x geeft er een opmaakvlag achteraan
        received.append((message, tag, level))

    signal = _log_signal()
    signal.connect(record)
    try:
        log = plugin_log("proef")
        log.info("alles goed")
        log.warning("let op")
        log.error("mis")
    finally:
        signal.disconnect(record)

    assert received, "geen enkele logregel bereikte het logpaneel"
    assert [(tag, level) for _m, tag, level in received[-3:]] == [
        (LOG_TAB, Qgis.MessageLevel.Info), (LOG_TAB, Qgis.MessageLevel.Warning),
        (LOG_TAB, Qgis.MessageLevel.Critical)]
    assert received[-1][0] == "[qgis ERROR proef] mis"


def test_debug_lines_stay_out_of_the_message_log_by_default(qgs_app):
    """Per item DEBUG is voor wie het aanzet; het logpaneel krijgt standaard de fasesamenvattingen."""
    from desktopstudie.qgis.task import plugin_log

    received = []

    def record(message, tag, level, *_format):
        received.append(message)

    signal = _log_signal()
    signal.connect(record)
    try:
        plugin_log("proef").debug("per item")
        plugin_log("proef").info("wel een fasesamenvatting")  # bewijst dat er geluisterd wordt
    finally:
        signal.disconnect(record)

    assert any("wel een fasesamenvatting" in message for message in received)
    assert not any("per item" in message for message in received)


# --- de runner: van Start tot de melding waar het rapport staat -------------------------------------

def _pipeline_result(result, pdf, failures=()):
    from desktopstudie.qgis.pipeline import PipelineResult

    return PipelineResult(result, None, pdf, None, None, [], 1, list(failures),
                          [("Layout", 0.1)])


def test_the_runner_finishes_on_the_main_thread_with_what_the_worker_fetched(qgs_app, tmp_path,
                                                                            monkeypatch):
    """Start -> werkthread (kern + netwerkhelft) -> hoofdthread (`finish`, met de voorbereiding van
    de werker en een should_cancel dat de GUI laat ademen) -> succesmelding met "Open PDF", canvas
    op de zone, en het `finished`-signaal met het resultaat."""
    from qgis.core import Qgis, QgsProject, QgsRectangle
    from qgis.PyQt.QtWidgets import QPushButton

    from desktopstudie.qgis import pipeline
    from desktopstudie.qgis.task import OPEN_PDF, StudyRunner

    request = _request(tmp_path)
    result, prepared = _fake_result(request.zone), _fake_prepared()
    seen = {}

    def fake_finish(project, res, meta, out_dir, log, progress=None, legends=False, should_cancel=None,
                    client=None, cache_mode="use", pngs=False, study_groups=True, prepared=None,
                    compact=False):
        seen.update(thread=threading.current_thread().name, prepared=prepared, project=project,
                    legends=legends, compact=compact, cancel=should_cancel(),
                    frozen=iface.canvas.isFrozen())
        progress(0.5, "Layout")
        pdf = tmp_path / "rapport.pdf"
        pdf.write_bytes(b"%PDF-1.4")
        return _pipeline_result(res, pdf)

    monkeypatch.setattr(pipeline, "run_core", lambda *args, **kwargs: result)
    monkeypatch.setattr(pipeline, "prepare", lambda *args, **kwargs: prepared)
    monkeypatch.setattr(pipeline, "finish", fake_finish)
    iface = FakeIface()
    runner = StudyRunner(iface, _log([]))
    done = []
    runner.finished.connect(done.append)

    runner.start(request)
    assert runner.running
    _wait_until(lambda: done)

    assert seen["thread"] == threading.current_thread().name, "finish hoort op de hoofdthread"
    assert seen["prepared"] is prepared and seen["project"] is QgsProject.instance()
    assert seen["legends"] is False and seen["cancel"] is False
    assert seen["compact"] is False, "de compacte opmaak reist mee uit de instellingen"
    # Every layer added to the open project would otherwise start a render that pulls tiles on
    # the main thread; the canvas is frozen for the project half and refreshed once at the end.
    assert seen["frozen"] is True and not iface.canvas.isFrozen()
    assert done[0].pdf == tmp_path / "rapport.pdf" and not runner.running
    levels = [level for level, _text, _item in iface.pushed]
    assert levels == [Qgis.MessageLevel.Info, Qgis.MessageLevel.Success], iface.pushed
    _level, text, item = iface.pushed[-1]
    assert "rapport.pdf" in text
    assert OPEN_PDF in [button.text() for button in item.findChildren(QPushButton)]
    assert iface.canvas.extent().contains(QgsRectangle(*request.zone.bbox))


def test_cancel_on_the_main_thread_stops_at_the_next_poll_with_a_message(qgs_app, tmp_path, monkeypatch):
    """De knop Annuleren tijdens de hoofdthread-helft: bij de eerstvolgende should_cancel stopt de
    run, de gebruiker leest "Studie afgebroken." en `finished` draagt None."""
    from qgis.core import Qgis

    from desktopstudie.core.parallel import Cancelled
    from desktopstudie.qgis import pipeline
    from desktopstudie.qgis.task import StudyRunner

    request = _request(tmp_path)
    monkeypatch.setattr(pipeline, "run_core", lambda *args, **kwargs: _fake_result(request.zone))
    monkeypatch.setattr(pipeline, "prepare", lambda *args, **kwargs: _fake_prepared())

    def finish_that_gets_cancelled(*args, should_cancel=None, **kwargs):
        runner.cancel()  # as the button does, between two phases
        if should_cancel():
            raise Cancelled("afgebroken door de gebruiker")
        raise AssertionError("should_cancel hoort de knop te zien")

    monkeypatch.setattr(pipeline, "finish", finish_that_gets_cancelled)
    iface = FakeIface()
    lines = []
    runner = StudyRunner(iface, _log(lines))
    done = []
    runner.finished.connect(done.append)

    runner.start(request)
    _wait_until(lambda: done)

    assert done == [None] and not runner.running
    assert iface.pushed[-1][:2] == (Qgis.MessageLevel.Warning, "Studie afgebroken.")
    assert any("afgebroken" in line for line in lines)


def test_a_failure_in_the_worker_and_failed_sources_are_named_to_the_user(qgs_app, tmp_path, monkeypatch):
    """Wat de headless runner met afsluitcode 3 zegt, zegt de plugin in de berichtenbalk: een
    mislukt product en de bronnen die niet antwoordden, bij naam. En een kern die omvalt is een
    rode melding, geen stilte."""
    from qgis.core import Qgis

    from desktopstudie.core.model import Provenance
    from desktopstudie.qgis import pipeline
    from desktopstudie.qgis.task import StudyRunner

    request = _request(tmp_path)
    result = _fake_result(request.zone)
    result.provenance = [Provenance("DHMV II relief", "https://dhmv", "2026-09-16T10:00:00", False, "plat"),
                         Provenance("Legenda Bodemkaart", "https://dov", "2026-09-16T10:00:00", False, "plat")]
    monkeypatch.setattr(pipeline, "run_core", lambda *args, **kwargs: result)
    monkeypatch.setattr(pipeline, "prepare", lambda *args, **kwargs: _fake_prepared())
    monkeypatch.setattr(pipeline, "finish",
                        lambda *args, **kwargs: _pipeline_result(result, None, ["PDF-export: FileError"]))
    iface = FakeIface()
    runner = StudyRunner(iface, _log([]))
    done = []
    runner.finished.connect(done.append)

    runner.start(request)
    _wait_until(lambda: done)

    warnings = [text for level, text, _item in iface.pushed if level == Qgis.MessageLevel.Warning]
    assert any("Rapport niet gemaakt" in text and "FileError" in text for text in warnings), warnings
    assert any("2 bron(nen)" in text and "DHMV II relief" in text and "Legenda Bodemkaart" in text
               for text in warnings), warnings

    def broken(*args, **kwargs):
        raise RuntimeError("DOV WFS antwoordt niet")

    monkeypatch.setattr(pipeline, "run_core", broken)
    runner.start(request)
    _wait_until(lambda: len(done) == 2)

    assert done[1] is None
    assert iface.pushed[-1][:2] == (Qgis.MessageLevel.Critical, "Studie mislukt: DOV WFS antwoordt niet")


def test_dismissing_the_progress_message_never_breaks_the_run(qgs_app, tmp_path, monkeypatch):
    """De gebruiker mag het voortgangsbericht wegklikken. QGIS verwijdert het item dan; de run gaat
    door zonder balk (alleen het log), meldt haar rapport en geeft Start weer vrij."""
    from qgis.core import Qgis
    from qgis.PyQt.QtCore import QCoreApplication, QEvent

    from desktopstudie.qgis import pipeline
    from desktopstudie.qgis.task import StudyRunner

    request = _request(tmp_path)
    result = _fake_result(request.zone)
    monkeypatch.setattr(pipeline, "run_core", lambda *args, **kwargs: result)
    monkeypatch.setattr(pipeline, "prepare", lambda *args, **kwargs: _fake_prepared())

    def finish_while_the_bar_is_closed(project, res, meta, out_dir, log, progress=None, should_cancel=None,
                                       **kwargs):
        iface.bar.popWidget(iface.bar.currentItem())  # what the close button of the message does
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        progress(0.5, "Layout")  # the item is gone; this must not raise
        assert should_cancel() is False
        pdf = tmp_path / "rapport.pdf"
        pdf.write_bytes(b"%PDF-1.4")
        return _pipeline_result(res, pdf)

    monkeypatch.setattr(pipeline, "finish", finish_while_the_bar_is_closed)
    iface = FakeIface()
    lines = []
    runner = StudyRunner(iface, _log(lines))
    done = []
    runner.finished.connect(done.append)

    runner.start(request)
    _wait_until(lambda: done)

    assert done[0] is not None and done[0].pdf == tmp_path / "rapport.pdf"
    assert not runner.running
    assert iface.pushed[-1][0] == Qgis.MessageLevel.Success
    assert not any("ERROR" in line for line in lines), lines


def test_a_failure_after_the_report_does_not_leave_the_user_without_a_message(qgs_app, tmp_path,
                                                                             monkeypatch):
    """Een fout na het rapport laat de gebruiker niet zonder bericht.

    De PDF staat er, maar het zoomen of het melden valt om: het logpaneel is dan de enige plek
    waar dat staat, en daar kijkt niemand uit zichzelf. De berichtenbalk hoort het te zeggen.
    """
    from qgis.core import Qgis

    from desktopstudie.qgis import pipeline
    from desktopstudie.qgis.task import StudyRunner

    class _IfaceWithoutCanvas(FakeIface):
        def mapCanvas(self):
            raise RuntimeError("canvas weg")

    request = _request(tmp_path)
    result = _fake_result(request.zone)
    pdf = tmp_path / "rapport.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    monkeypatch.setattr(pipeline, "run_core", lambda *args, **kwargs: result)
    monkeypatch.setattr(pipeline, "prepare", lambda *args, **kwargs: _fake_prepared())
    monkeypatch.setattr(pipeline, "finish", lambda *args, **kwargs: _pipeline_result(result, pdf))
    iface = _IfaceWithoutCanvas()
    runner = StudyRunner(iface, _log([]))
    done = []
    runner.finished.connect(done.append)

    runner.start(request)
    _wait_until(lambda: done)

    critical = [text for level, text, _item in iface.pushed if level == Qgis.MessageLevel.Critical]
    assert critical, [(level, text) for level, text, _item in iface.pushed]
    assert "canvas weg" in critical[-1]


def test_a_failure_while_reporting_the_result_is_logged_and_finished_still_fires(qgs_app, tmp_path,
                                                                                monkeypatch):
    """Zoomen of melden dat misgaat mag de dialoog niet in de wacht laten: de fout staat in het log,
    `finished` komt met het resultaat, en de runner is klaar voor de volgende studie."""
    from desktopstudie.qgis import pipeline
    from desktopstudie.qgis.task import StudyRunner

    class _IfaceWithoutCanvas(FakeIface):
        def mapCanvas(self):
            raise RuntimeError("canvas weg")

    request = _request(tmp_path)
    result = _fake_result(request.zone)
    pdf = tmp_path / "rapport.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    monkeypatch.setattr(pipeline, "run_core", lambda *args, **kwargs: result)
    monkeypatch.setattr(pipeline, "prepare", lambda *args, **kwargs: _fake_prepared())
    monkeypatch.setattr(pipeline, "finish", lambda *args, **kwargs: _pipeline_result(result, pdf))
    iface = _IfaceWithoutCanvas()
    lines = []
    runner = StudyRunner(iface, _log(lines))
    done = []
    runner.finished.connect(done.append)

    runner.start(request)
    _wait_until(lambda: done)

    assert done[0] is not None and done[0].pdf == pdf
    assert any("ERROR" in line and "canvas weg" in line for line in lines), lines
    assert not runner.running
