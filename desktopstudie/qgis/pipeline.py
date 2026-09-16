"""One study end to end: core run -> prefetches -> relief -> layers -> files -> report -> PDF.

Split in three on purpose. `run_core` is everything that only needs Python and the network;
`prepare` is the shell's own share of that - the legend images, the quartair drawings and the map
images, planned from the study without a single layer - so both run on a worker thread in the
plugin (its QgsTask); `finish` is everything that touches QGIS map layers, a layout and a project,
which has to happen on the main thread, and it runs `prepare` itself when nobody did. What stays on
the main thread yields between phases, between pages of the layout and between runs of the
exporter, through the `should_cancel` it is handed. `run_pipeline` is all of it in one call; the
headless script drives the halves itself, because it reports how long each took.

Four things are easy to get wrong here and are therefore done in one place.

*The durable products come first.* The GeoPackage and the standalone project are written before
the PDF. Rendering ninety-five sheets is the longest and most fragile step of a study, and a run
that falls over there must still leave the user the data it already gathered - so a failed PDF is
a `failures` entry and `pdf is None`, not an exception that throws the whole study away.

*Everything the shell consults is a source too.* The DTM, every WMS layer, every legend: each gets
a `Provenance` entry, ok or not. That is why the checks run after those phases - `check_sources`
turns a failed source into a signalering, so the report names the map that is missing instead of
quietly printing a page without a background.

*The rules run twice.* The core already filled `signaleringen`, but the relief only arrives here
and the relief rule cannot fire without it. So `checks.run_all` runs again over the completed
result, and the two signals only the orchestrator could know (a truncated WFS list, failed
doorprik points) are carried over, because nothing in the data can rebuild them.

*The open project is not the deliverable.* The study's groups go into the project the user has
open, but the `.qgz` next to the PDF is a FRESH project built from the GeoPackage, so the file
still works weeks later, on another machine, without this session.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set, Tuple

from qgis.core import QgsMapLayer, QgsProject

from ..core import catalogue, checks
from ..core.catalogue import DHMV_WCS_URL
from ..core.logging_util import Log
from ..core.model import Provenance, StudyResult, StudyZone, now_iso
from ..core.report_content import Report, ReportMeta, build_report, profile_image_key
from ..core.services.http import HttpClient
from ..core.study import JSON_RELATIVE, Settings, StudyCancelled, orchestrator_signals
from ..core.study import run as run_study
from . import compat, dem, export, layers
from . import layout as layout_mod

# chapter in the catalogue -> the group title in the project, numbered as the report numbers its
# chapters so the layer panel reads in the same order as the PDF.
CHAPTER_GROUPS = {"ligging": "1 Ligging en topografie", "historisch": "2 Historische kaarten",
                  "geologie": "3 Geologie en bodem"}
PDF_NAME = "rapport.pdf"
PAGES_DIR = "paginas"
PROJECT_NAME = "studie.qgz"
GPKG_NAME = "studie.gpkg"
JSON_NAME = "studie.json"
DATA_DIR = "data"
CACHE_DIR = "cache"
RELIEF_SOURCE = "DHMV II relief"
# Marks the copies the report maps draw with. They live outside the layer tree, so nobody can
# remove them by hand; the flag lets a second run clean up after the first.
REPORT_OVERLAY_FLAG = "desktopstudie/report_overlay"
# Page PNGs are rendered at the PDF's resolution on purpose: QGIS keeps fetched WMS tiles per
# request URL, and that URL carries the pixel size. A different dpi asks every service for every
# tile a second time, which is minutes on a study of ninety-five sheets.
PAGE_PNG_DPI = export.PDF_DPI
# How much of a whole run the core half is worth on the progress bar. Roughly right for a study of
# a few hundred fiches; the point is only that the bar keeps moving forward.
CORE_SHARE = 0.5


@dataclass
class PipelineResult:
    result: StudyResult
    report: Report
    # Three of the four products can be missing when their step failed; `failures` then says
    # which and why. `result` and `report` are always there - they are in memory by then.
    pdf: Optional[Path]
    project_file: Optional[Path]
    geopackage: Optional[Path]
    page_pngs: List[Path]
    failures: List[str] = field(default_factory=list)
    # (phase, seconds) in the order they ran. A study of half an hour has to be able to say WHERE
    # the time went; the plugin's progress bar needs the same split.
    timings: List[Tuple[str, float]] = field(default_factory=list)


def make_client(out_dir, log: Log, cache_mode: str = "use") -> HttpClient:
    """The HTTP client for one study: one disk cache per output directory, so a second phase (the
    legends) re-uses what the first phase already fetched and a re-run costs nothing."""
    return HttpClient(cache_dir=Path(out_dir) / DATA_DIR / CACHE_DIR, log=log.child("http"),
                      cache_mode=cache_mode)


def run_core(zone: StudyZone, settings: Settings, out_dir: Path, log: Log, progress=None,
             should_cancel=None, cache_mode: str = "use",
             client: Optional[HttpClient] = None) -> StudyResult:
    """The part of a study that never touches QGIS: data, figures and studie.json."""
    out_dir = Path(out_dir)
    client = client or make_client(out_dir, log, cache_mode)
    return run_study(zone, settings, client, out_dir, progress=progress, log=log.child("study"),
                     should_cancel=should_cancel)


# --- the sources the shell consults ---------------------------------------------------------------

def record_source(result: StudyResult, source: str, url: str, ok: bool = True,
                  message: str = "") -> None:
    """Record (or replace) what the shell consulted, so `check_sources` can report on it.

    Replacing rather than appending keeps a second `finish` on the same result honest: the plugin
    can re-run a study after a service comes back up, and two contradicting lines about the same
    source in the sources chapter would be worse than none.
    """
    entry = Provenance(source, url, now_iso(), ok, message)
    for index, existing in enumerate(result.provenance):
        if existing.source == source:
            result.provenance[index] = entry
            return
    result.provenance.append(entry)


class PhaseClock:
    """Wall clock per phase of a run, in the order the phases happened.

    It replaces the bare progress callback: every phase announces itself exactly once, and the
    announcement is also the moment the previous phase is closed. "It was slow" is not a diagnosis,
    and a table of seconds per phase is the difference between guessing and knowing.
    """

    def __init__(self, progress: Callable[[float, str], None], log: Log):
        self._progress, self._log = progress, log
        self.timings: List[Tuple[str, float]] = []
        self._name: Optional[str] = None
        self._started = 0.0

    def begin(self, fraction: float, name: str) -> None:
        self.close()
        self._name, self._started = name, time.monotonic()
        self._progress(fraction, name)

    def close(self) -> None:
        if self._name is not None:
            self.timings.append((self._name, time.monotonic() - self._started))
            self._name = None

    def report(self) -> None:
        """Log the table, slowest phase named last so it is the line that stays on screen."""
        if not self.timings:
            return
        total = sum(seconds for _name, seconds in self.timings)
        for name, seconds in self.timings:
            self._log.info(f"fase {name}: {seconds:.1f} s")
        slowest, worst = max(self.timings, key=lambda item: item[1])
        self._log.info(f"fase totaal: {total:.1f} s; traagste fase {slowest} ({worst:.1f} s)")


def _stop_if_cancelled(should_cancel: Optional[Callable[[], bool]]) -> None:
    if should_cancel is not None and should_cancel():
        raise StudyCancelled("afgebroken door de gebruiker")


def _measure_relief(result: StudyResult, zone_layer: QgsMapLayer, log: Log, should_cancel) -> None:
    """Sample the DTM over the zone, and record the DHMV as a source either way.

    The zone layer comes from the caller rather than being built here: it is the same polygon that
    goes on every map page and into the GeoPackage, and `relief_of_zone` samples a clone of it, so
    a second layer would only be a second object saying the same thing.

    A zone that is genuinely flat and a service that is down both leave `relief` empty; only the
    provenance tells them apart, and that difference is the reader's. A cancelled measurement
    leaves it empty too, which is why the stop is checked before anything is recorded: a user who
    pressed cancel must not find "DHMV niet beschikbaar" in a later report.
    """
    result.relief = dem.relief_of_zone(zone_layer, log.child("dem"), should_cancel)
    _stop_if_cancelled(should_cancel)
    ok = result.relief is not None
    record_source(result, RELIEF_SOURCE, DHMV_WCS_URL, ok,
                  "" if ok else "geen hoogtewaarden voor de zone (dienst of dekking)")


def _figured(result: StudyResult) -> set:
    """The permkeys of the investigations that got a figure in the report; those are the ones a
    report map labels."""
    return {key.split("_", 1)[1] for key in result.figures if key.startswith(("cpt_", "boring_"))}


def _study_overlays(result: StudyResult) -> Dict[str, List[QgsMapLayer]]:
    """The layers a map page can ask to draw on top of a catalogue map. These are the ones the user
    gets in the layer panel and the ones written to the GeoPackage: every point labelled."""
    figured = _figured(result)
    return {"zone": [layers.zone_layer(result.zone)],
            "section": [layers.line_layer(result.zone)],
            "investigations": [layers.points_layer("sondering", result.cpts, figured),
                               layers.points_layer("boring", result.boreholes, figured),
                               layers.points_layer("peilput", result.gw_filters, figured),
                               layers.circle_layer(result.zone)]}


def _report_overlays(project: QgsProject, overlays: Dict[str, List[QgsMapLayer]]
                     ) -> Dict[str, List[QgsMapLayer]]:
    """The same layers again, styled for paper: only the investigations with a figure are labelled.

    Copies rather than a restyle of the originals, because the user's own layers keep every number
    - on screen you can zoom, on paper two hundred labels are a grey smudge. The copies are
    registered in the project without a tree node: invisible in the layer panel, but part of the
    project, so a layout saved with that project still finds the layers its maps point at.
    """
    report: Dict[str, List[QgsMapLayer]] = {}
    for key, group in overlays.items():
        copies = []
        for layer in group:
            copy = layer.clone()
            copy.setName(layer.name())
            copy.setCustomProperty(REPORT_OVERLAY_FLAG, True)
            kind = next((k for k, title in layers.POINT_NAMES.items() if title == layer.name()), None)
            if kind is not None:
                layers.style_points_layer(copy, kind, label_only_figured=True)
            project.addMapLayer(copy, False)
            copies.append(copy)
        report[key] = copies
    return report


def drop_previous_run(project: QgsProject, keep=()) -> None:
    """Remove what an earlier study in this session left behind: its layout and the copies its
    maps drew with.

    In that order. The copies live outside the layer tree, so nobody can remove them by hand, and
    removing them while the old layout still points at them would leave a layout referring to
    layers that are gone. `keep` is what THIS run has already built and is about to draw with.
    """
    manager = project.layoutManager()
    existing = manager.layoutByName(layout_mod.LAYOUT_NAME)
    if existing is not None:
        manager.removeLayout(existing)
    spared = {layer.id() for layer in keep}
    stale = [layer.id() for layer in project.mapLayers().values()
             if layer.customProperty(REPORT_OVERLAY_FLAG) and layer.id() not in spared]
    if stale:
        project.removeMapLayers(stale)


def _map_layers_into_groups(project: QgsProject, result: StudyResult,
                            log: Log) -> Dict[str, List[QgsMapLayer]]:
    """Load every catalogue map as a WMS layer, group it in the project and index it by map id.

    A layer that does not come back valid (an unreachable service) costs its own map page, not the
    report: it is left out, logged, and recorded as a failed source so the report names it.
    """
    layers_by_map: Dict[str, List[QgsMapLayer]] = {}
    for chapter, title in CHAPTER_GROUPS.items():
        group_layers: List[QgsMapLayer] = []
        entries = catalogue.entries(chapter)
        for entry in entries:
            layer = layers.wms_layer(entry)
            if not layer.isValid():
                log.warning(f"WMS-laag niet geldig: {entry.id} ({entry.wms_url})")
                record_source(result, f"Kaartlaag {entry.title}", entry.wms_url, False,
                              "WMS-laag ongeldig; kaartpagina zonder ondergrond")
                continue
            record_source(result, f"Kaartlaag {entry.title}", entry.wms_url, True)
            layers_by_map[entry.id] = [layer]
            group_layers.append(layer)
        layers.add_group(project, title, group_layers, visible=False)
        log.info(f"{title}: {len(group_layers)} van {len(entries)} kaarten geladen")
    return layers_by_map


def _fetch_legends(result: StudyResult, out_dir: Path, client: HttpClient, log: Log,
                   should_cancel) -> Dict[str, Path]:
    """Every legend image, with the misses recorded as failed sources."""
    images, _missing = layout_mod.prepare_legends(catalogue.entries(), out_dir, client,
                                                  log.child("legendas"), should_cancel)
    for entry in catalogue.entries():
        if not entry.legend:
            continue
        found = entry.id in images
        record_source(result, f"Legenda {entry.title}",
                      layout_mod.wms_legend_url(entry, entry.legend_options), found,
                      "" if found else "legenda niet opgehaald; kaart zonder legendapagina")
    return images


def _fetch_zone_legends(result: StudyResult, targets: Dict[str, str], out_dir: Path,
                        client: HttpClient, log: Log, should_cancel) -> Dict[str, str]:
    """The quartair drawings, keyed as `report_content` looks them up, relative to `out_dir`.

    That is the shape `build_report` wants and the same one `StudyResult.figures` already uses, so
    the layout resolves both the same way. Every drawing is a source of its own: one that did not
    come back is named in the sources chapter rather than quietly missing from the legend.
    """
    images = layout_mod.prepare_zone_legend_images(result, out_dir, client, log.child("legendas"),
                                                   should_cancel)
    for url, code in targets.items():
        found = profile_image_key(code) in images
        record_source(result, f"Legenda profieltype {code}", url, found,
                      "" if found else "tekening van het profieltype niet opgehaald of niet leesbaar")
    return {key: path.relative_to(out_dir).as_posix() for key, path in images.items()}


NO_COVERAGE_MESSAGE = "geen dekking op deze locatie"


MAP_IMAGE_SOURCE = "Kaartbeeld"


def _fetch_map_images(result: StudyResult, requests: List[layout_mod.MapRequest], out_dir: Path,
                      client: HttpClient, log: Log, should_cancel) -> Tuple[Dict[str, Path], Set[str]]:
    """Every map page's background, fetched up front: {key -> PNG on disk}, and the maps that
    drew nothing here.

    One GetMap per distinct box, all of them in flight together, instead of the WMS provider
    pulling tiles while each of ninety sheets renders. Each image is a source of its own, and an
    image that is empty answers the coverage question for free - for maps without facts, where an
    empty tile really does mean "no sheet here". Pure HTTP and files: this is worker-thread work.
    """
    images, empty = layout_mod.prepare_map_images(requests, out_dir, client, log.child("kaarten"),
                                                  should_cancel)
    for request in requests:
        entry = catalogue.by_id(request.map_id)
        found = request.key in images
        message = ("" if request.map_id not in empty else NO_COVERAGE_MESSAGE) if found else \
            "kaartbeeld niet opgehaald; kaartpagina zonder ondergrond"
        record_source(result, f"{MAP_IMAGE_SOURCE} {entry.title}",
                      layout_mod.wms_map_url(entry, request.extent, request.width, request.height),
                      found, message)
    return images, empty


def _snapshot_layers(project: QgsProject, requests: List[layout_mod.MapRequest],
                     images: Dict[str, Path]) -> Dict[str, QgsMapLayer]:
    """The fetched images as raster layers the layout draws, registered in `project` without a
    tree node and flagged so a later run can clean them up. Main-thread work: layers and project."""
    snapshots: Dict[str, QgsMapLayer] = {}
    for request in requests:
        path = images.get(request.key)
        if path is None:
            continue
        layer = layers.snapshot_layer(path, f"{catalogue.by_id(request.map_id).title} (kaartbeeld)")
        layer.setCustomProperty(REPORT_OVERLAY_FLAG, True)
        project.addMapLayer(layer, False)
        snapshots[request.key] = layer
    return snapshots


def _install_layout(project: QgsProject, lay, log: Log) -> None:
    """Hand the layout to the project's layout manager, replacing the one from an earlier run.

    The manager takes ownership, and when it refuses (a name it already holds) it DELETES the
    layout it was handed - verified on 3.40.15: the next call on the wrapper raises "wrapped C/C++
    object has been deleted". So a refusal ends the run here, with a sentence that says what
    happened, rather than two lines further on in freed memory.
    """
    if not project.layoutManager().addLayout(lay):
        raise RuntimeError(f"Layout {layout_mod.LAYOUT_NAME} kon niet aan het project worden "
                           f"toegevoegd; staat er al een layout met die naam?")


def _guarded(what: str, failures: List[str], log: Log, run: Callable[[], object]):
    """Run one step that writes a product; a failure costs that product, not the study.

    The data products are already on disk by the time this runs, so an export that falls over is
    reported and the run finishes - the caller hands the user what there is.
    """
    try:
        return run()
    except StudyCancelled:
        raise  # a cancelled run is not a broken product
    except Exception as exc:  # noqa: BLE001 - the study keeps what it has already written
        failures.append(f"{what}: {exc}")
        log.error(f"{what} mislukt: {exc}")
        return None


@dataclass
class Prepared:
    """What the shell fetched from the network for one study, before it touches QGIS. Every
    field is plain Python or a file on disk, so it crosses from the worker thread to the main
    thread as data."""
    legend_images: Dict[str, Path]  # map id -> legend PNG
    zone_legend_images: Dict[str, str]  # as `build_report` wants them, relative to out_dir
    map_images: Dict[str, Path]  # `map_image_key` -> PNG with its world file next to it
    no_coverage: Set[str]  # map ids whose service drew nothing here
    requests: List[layout_mod.MapRequest]  # what was asked for, in page order
    timings: List[Tuple[str, float]]


def prepare(result: StudyResult, meta: ReportMeta, out_dir, log: Log,
            progress: Optional[Callable[[float, str], None]] = None,
            should_cancel: Optional[Callable[[], bool]] = None, client: Optional[HttpClient] = None,
            cache_mode: str = "use", legends: bool = True) -> Prepared:
    """The shell's network half: legends, the quartair drawings and the map images.

    No project, no map layer, nothing that needs the GUI thread - the map images are planned on
    boxes read from the study (`layout.overlay_boxes`), which is why the plugin can run this on
    its worker right after `run_core`. Every fetch records its source on `result`, ok or not.

    The quartair drawings are report content, not legend sheets, so they are fetched whatever
    `legends` says: without them the quartair chapter has a table of numbers and nothing that
    says what those numbers look like. A study whose zone holds no quartair rows asks nothing.
    """
    out_dir = Path(out_dir)
    clock = PhaseClock(progress or (lambda fraction, message: None), log)

    legend_images: Dict[str, Path] = {}
    if legends:
        _stop_if_cancelled(should_cancel)
        clock.begin(0.02, "Legendas")
        client = client or make_client(out_dir, log, cache_mode)
        legend_images = _fetch_legends(result, out_dir, client, log, should_cancel)

    zone_legend_images: Dict[str, str] = {}
    targets = layout_mod.zone_legend_targets(result)
    if targets:
        _stop_if_cancelled(should_cancel)
        clock.begin(0.12, "Tekeningen van de profieltypes")
        client = client or make_client(out_dir, log, cache_mode)
        zone_legend_images = _fetch_zone_legends(result, targets, out_dir, client, log, should_cancel)

    _stop_if_cancelled(should_cancel)
    clock.begin(0.14, "Kaartbeelden")
    client = client or make_client(out_dir, log, cache_mode)
    # Which boxes to fetch follows from the map pages, and those follow from the catalogue and the
    # zone - not from the signaleringen. So the tree is built once here to be read, and once in
    # `finish` to be printed, with every source of this study in it. Building it is pure Python.
    planned = build_report(result, meta, zone_legend_images)
    requests = layout_mod.plan_map_images(planned, result.zone.ring, layout_mod.overlay_boxes(result))
    map_images, no_coverage = _fetch_map_images(result, requests, out_dir, client, log, should_cancel)
    clock.close()
    return Prepared(legend_images, zone_legend_images, map_images, no_coverage, requests,
                    clock.timings)


# The PDF phase on the progress bar: from `PDF_START` to `PDF_END` the export reports per run.
PDF_START, PDF_END = 0.50, 0.95


def finish(project: QgsProject, result: StudyResult, meta: ReportMeta, out_dir, log: Log,
           progress: Optional[Callable[[float, str], None]] = None, legends: bool = True,
           should_cancel: Optional[Callable[[], bool]] = None, client: Optional[HttpClient] = None,
           cache_mode: str = "use", pngs: bool = False, study_groups: bool = True,
           prepared: Optional[Prepared] = None) -> PipelineResult:
    """Main-thread part: relief, layers, files, report, layout, exports - on what `prepare` fetched.

    `prepared` is the network half, already done on a worker thread by the plugin; left None it is
    done here first, on the calling thread (the headless script, `run_pipeline`). Either way the
    phase table covers both halves.

    `project` is the project the layers and the layout go into - the one the user has open in the
    plugin, a fresh one headless. The standalone `.qgz` is built separately, from the GeoPackage.
    `pngs` writes every page as an image as well; off by default, because it renders the whole
    report a second time for a product nobody asked for.

    `study_groups` puts the catalogue maps in `project` as live WMS layers. That is what the plugin
    wants - the user carries on working in that project - and what a headless run does not: nobody
    ever sees that QgsProject, while building the layers costs a GetCapabilities per map (2,6 s
    each against DOV, measured 2026-09-16). The deliverable `.qgz` gets them either way.
    """
    out_dir = Path(out_dir)
    progress = progress or (lambda fraction, message: None)
    clock = PhaseClock(progress, log)
    report_progress = clock.begin
    compat.ensure_font_dir(log)
    failures: List[str] = []

    if prepared is None:
        prepared = prepare(result, meta, out_dir, log, progress, should_cancel, client, cache_mode,
                           legends)
    clock.timings.extend(prepared.timings)

    _stop_if_cancelled(should_cancel)
    report_progress(0.28, "Relief uit DHMV")
    # The study's own layers first: the zone polygon among them is what the relief is measured on.
    overlays = _study_overlays(result)
    _measure_relief(result, overlays["zone"][0], log, should_cancel)

    _stop_if_cancelled(should_cancel)
    report_progress(0.30, "Lagen")
    layers_by_map = _map_layers_into_groups(project, result, log) if study_groups else {}
    layers.add_group(project, layers.ZONE_GROUP, overlays["zone"] + overlays["section"])
    layers.add_group(project, layers.INVESTIGATION_GROUP, overlays["investigations"])
    report_overlays = _report_overlays(project, overlays)
    map_images = _snapshot_layers(project, prepared.requests, prepared.map_images)

    # From cheap to expensive, so that whatever falls over, what came before it is on disk.
    _stop_if_cancelled(should_cancel)
    report_progress(0.31, "Signaleringen en rapport")
    # Every source the shell consulted is recorded by now, so the rules see the whole study.
    result.signaleringen = checks.validate(checks.run_all(result) + orchestrator_signals(result))
    json_path = out_dir / DATA_DIR / JSON_NAME
    json_path.parent.mkdir(parents=True, exist_ok=True)  # nothing below creates a folder for us
    record_source(result, "studie.json", JSON_RELATIVE)  # stamped before the write it describes
    result.write_json(json_path)
    report = build_report(result, meta, prepared.zone_legend_images)

    report_progress(0.33, "GeoPackage en projectbestand")
    gpkg = out_dir / DATA_DIR / GPKG_NAME
    # A GeoPackage still open in another QGIS is the everyday failure of a second run, and it must
    # not cost the report: the data is in studie.json above either way.
    written = _guarded("GeoPackage schrijven", failures, log, lambda: layers.write_geopackage(
        overlays["zone"] + overlays["section"] + overlays["investigations"], gpkg,
        project.transformContext()) or gpkg)
    project_file = None
    if written is not None:
        standalone = layers.standalone_project(
            gpkg, CHAPTER_GROUPS, log,
            {map_id: group[0] for map_id, group in layers_by_map.items()})
        project_file = _guarded("Projectbestand schrijven", failures, log,
                                lambda: export.write_project(standalone, out_dir / PROJECT_NAME))
    log.info(f"Rapport: {len(report.chapters)} hoofdstukken, "
             f"{sum(len(chapter.pages) for chapter in report.chapters)} pagina's")

    _stop_if_cancelled(should_cancel)
    report_progress(0.38, "Layout")
    # Everything THIS run has already put in the project - the styled copies and the map images -
    # is spared; they were made minutes ago and the layout below is about to draw with them.
    drop_previous_run(project, keep=list(map_images.values())
                      + [layer for group in report_overlays.values() for layer in group])
    # The same boxes the images were planned on, so every page finds the image fetched for it.
    lay = layout_mod.build_layout(project, report, report_overlays,
                                  out_dir, result.zone.ring, report.meta, legends=legends,
                                  legend_images=prepared.legend_images, log=log.child("layout"),
                                  should_cancel=should_cancel, no_coverage=prepared.no_coverage,
                                  map_images=map_images,
                                  overlay_boxes=layout_mod.overlay_boxes(result))
    _install_layout(project, lay, log)
    log.info(f"Layout: {lay.pageCollection().pageCount()} bladen")

    _stop_if_cancelled(should_cancel)
    # Stoppable between two runs of the exporter, never inside one: QgsLayoutExporter takes no
    # feedback object. A run is ten sheets, a few seconds.
    report_progress(PDF_START, "PDF-export")

    def pdf_progress(done: int, total: int) -> None:
        progress(PDF_START + (PDF_END - PDF_START) * done / max(total, 1),
                 f"PDF-export: {done}/{total} bladen")

    pdf = _guarded("PDF-export", failures, log,
                   lambda: export.export_pdf(lay, out_dir / PDF_NAME, should_cancel=should_cancel,
                                             progress=pdf_progress))
    page_pngs: List[Path] = []
    if pngs:
        report_progress(PDF_END, "Pagina's als PNG")
        page_pngs = _guarded("PNG-export", failures, log,
                                    lambda: export.export_pages_png(lay, out_dir / PAGES_DIR,
                                                                    PAGE_PNG_DPI)) or []
    clock.close()
    clock.report()
    progress(1.0, "Klaar")
    products = [name for name in (json_path.name, written.name if written else None,
                                  project_file.name if project_file else None,
                                  pdf.name if pdf else None) if name]
    log.info(f"Klaar: {', '.join(products)} in {out_dir}"
             + (f" ({len(failures)} mislukt)" if failures else ""))
    return PipelineResult(result, report, pdf, project_file, written, page_pngs, failures,
                          clock.timings)


def part_of(progress: Optional[Callable[[float, str], None]], low: float, high: float):
    """`progress` restricted to one stretch of the bar. Both halves report 0 -> 1 of their own
    work; handed the caller's callback unchanged, the bar would run full, jump back to zero and
    run full again. Public because the headless runner drives the two halves itself."""
    if progress is None:
        return None
    return lambda fraction, message: progress(low + (high - low) * fraction, message)


def run_pipeline(zone: StudyZone, settings: Settings, meta: ReportMeta, out_dir, project: QgsProject,
                 log: Log, progress: Optional[Callable[[float, str], None]] = None,
                 should_cancel: Optional[Callable[[], bool]] = None, cache_mode: str = "use",
                 legends: bool = True, pngs: bool = False) -> PipelineResult:
    """One study from zone to PDF, on the calling thread. The client is made once so both halves
    share the same disk cache."""
    out_dir = Path(out_dir)
    client = make_client(out_dir, log, cache_mode)
    result = run_core(zone, settings, out_dir, log, part_of(progress, 0.0, CORE_SHARE),
                      should_cancel, cache_mode, client)
    return finish(project, result, meta, out_dir, log, part_of(progress, CORE_SHARE, 1.0),
                  legends=legends, should_cancel=should_cancel, client=client, cache_mode=cache_mode,
                  pngs=pngs)
