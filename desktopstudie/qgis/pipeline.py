"""One study end to end: core run -> relief -> layers -> legends -> files -> report -> PDF.

Split in two on purpose. `run_core` is everything that only needs Python and the network, so it
can run on a worker thread (the plugin's QgsTask); `finish` is everything that touches QGIS map
layers, a layout and a project, which has to happen on the main thread. `run_pipeline` is the two
of them for a caller that has no threads to worry about - the headless script.

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

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

from qgis.core import QgsMapLayer, QgsProject

from ..core import catalogue, checks
from ..core.catalogue import DHMV_WCS_URL
from ..core.logging_util import Log
from ..core.model import Provenance, StudyResult, StudyZone, now_iso
from ..core.report_content import Report, ReportMeta, build_report
from ..core.services.http import HttpClient
from ..core.study import Settings, StudyCancelled, orchestrator_signals
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
    pdf: Optional[Path]  # None when the export failed; `failures` then says so
    project_file: Path
    geopackage: Path
    page_pngs: List[Path]
    failures: List[str] = field(default_factory=list)


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


def _stop_if_cancelled(should_cancel: Optional[Callable[[], bool]]) -> None:
    if should_cancel is not None and should_cancel():
        raise StudyCancelled("afgebroken door de gebruiker")


def _measure_relief(result: StudyResult, log: Log, should_cancel) -> None:
    """Sample the DTM over the zone, and record the DHMV as a source either way.

    A zone that is genuinely flat and a service that is down both leave `relief` empty; only the
    provenance tells them apart, and that difference is the reader's.
    """
    result.relief = dem.relief_of_zone(layers.zone_layer(result.zone), log.child("dem"), should_cancel)
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
            kind = next((k for k, title in layers.POINT_NAMES.items() if title == layer.name()), None)
            if kind is not None:
                layers.style_points_layer(copy, kind, label_only_figured=True)
            project.addMapLayer(copy, False)
            copies.append(copy)
        report[key] = copies
    return report


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


def _install_layout(project: QgsProject, lay, log: Log) -> None:
    """Hand the layout to the project's layout manager, replacing the one from an earlier run.

    Two layouts of the same name leave the user picking blind, and the manager takes ownership -
    after this the project keeps the layout alive, not us. `addLayout` refuses instead of raising,
    so its answer is checked: a silently missing layout is a plugin whose report button does
    nothing.
    """
    manager = project.layoutManager()
    existing = manager.layoutByName(layout_mod.LAYOUT_NAME)
    if existing is not None:
        manager.removeLayout(existing)
    if not manager.addLayout(lay):
        log.warning(f"Layout {layout_mod.LAYOUT_NAME} kon niet aan het project worden toegevoegd")


def _guarded_export(what: str, failures: List[str], log: Log, run: Callable[[], object]):
    """Run one export; a failure costs that product, not the study.

    The data products are already on disk by the time this runs, so an export that falls over is
    reported and the run finishes - the caller hands the user what there is.
    """
    try:
        return run()
    except Exception as exc:  # noqa: BLE001 - the study keeps what it has already written
        failures.append(f"{what}: {exc}")
        log.error(f"{what} mislukt: {exc}")
        return None


def finish(project: QgsProject, result: StudyResult, meta: ReportMeta, out_dir, log: Log,
           progress: Optional[Callable[[float, str], None]] = None, legends: bool = True,
           should_cancel: Optional[Callable[[], bool]] = None, client: Optional[HttpClient] = None,
           cache_mode: str = "use", pngs: bool = False) -> PipelineResult:
    """Main-thread part: relief, layers, legends, files, report, layout, exports.

    `project` is the project the layers and the layout go into - the one the user has open in the
    plugin, a fresh one headless. The standalone `.qgz` is built separately, from the GeoPackage.
    `pngs` writes every page as an image as well; off by default, because it renders the whole
    report a second time for a product nobody asked for.
    """
    out_dir = Path(out_dir)
    report_progress = progress or (lambda fraction, message: None)
    compat.ensure_font_dir(log)
    failures: List[str] = []

    _stop_if_cancelled(should_cancel)
    report_progress(0.02, "Relief uit DHMV")
    _measure_relief(result, log, should_cancel)

    _stop_if_cancelled(should_cancel)
    report_progress(0.05, "Lagen")
    overlays = _study_overlays(result)
    layers_by_map = _map_layers_into_groups(project, result, log)
    layers.add_group(project, layers.ZONE_GROUP, overlays["zone"] + overlays["section"])
    layers.add_group(project, layers.INVESTIGATION_GROUP, overlays["investigations"])

    _stop_if_cancelled(should_cancel)
    legend_images: Dict[str, Path] = {}
    if legends:
        report_progress(0.20, "Legendas")
        legend_images = _fetch_legends(result, out_dir, client or make_client(out_dir, log, cache_mode),
                                       log, should_cancel)

    # The durable products first: whatever happens to the rendering below, this is on disk.
    _stop_if_cancelled(should_cancel)
    report_progress(0.30, "GeoPackage")
    gpkg = out_dir / DATA_DIR / GPKG_NAME
    gpkg.parent.mkdir(parents=True, exist_ok=True)  # OGR creates the file, never the folder
    layers.write_geopackage(overlays["zone"] + overlays["section"] + overlays["investigations"], gpkg,
                            project.transformContext())
    report_progress(0.33, "Projectbestand")
    standalone = layers.standalone_project(gpkg, CHAPTER_GROUPS, log,
                                           {map_id: group[0] for map_id, group in layers_by_map.items()})
    project_file = export.write_project(standalone, out_dir / PROJECT_NAME)

    _stop_if_cancelled(should_cancel)
    report_progress(0.35, "Signaleringen en rapport")
    # Every source the shell consulted is recorded by now, so the rules see the whole study.
    result.signaleringen = checks.validate(checks.run_all(result) + orchestrator_signals(result))
    result.write_json(out_dir / DATA_DIR / JSON_NAME)
    report = build_report(result, meta)
    log.info(f"Rapport: {len(report.chapters)} hoofdstukken, "
             f"{sum(len(chapter.pages) for chapter in report.chapters)} pagina's")

    report_progress(0.38, "Layout")
    lay = layout_mod.build_layout(project, report, layers_by_map, _report_overlays(project, overlays),
                                  out_dir, result.zone.ring, report.meta, legends=legends,
                                  legend_images=legend_images, log=log.child("layout"),
                                  should_cancel=should_cancel)
    _install_layout(project, lay, log)
    log.info(f"Layout: {lay.pageCollection().pageCount()} bladen")

    _stop_if_cancelled(should_cancel)
    # The one step that cannot be interrupted: QgsLayoutExporter takes no feedback object, so a
    # cancel during the export is only honoured once it returns. The message says so.
    report_progress(0.50, "PDF-export (niet onderbreekbaar)")
    pdf = _guarded_export("PDF-export", failures, log,
                          lambda: export.export_pdf(lay, out_dir / PDF_NAME))
    page_pngs: List[Path] = []
    if pngs:
        report_progress(0.95, "Pagina's als PNG")
        page_pngs = _guarded_export("PNG-export", failures, log,
                                    lambda: export.export_pages_png(lay, out_dir / PAGES_DIR,
                                                                    PAGE_PNG_DPI)) or []
    report_progress(1.0, "Klaar")
    log.info(f"Klaar: {gpkg.name}, {project_file.name}, "
             f"{pdf.name if pdf else 'geen PDF'} in {out_dir}")
    return PipelineResult(result, report, pdf, project_file, gpkg, page_pngs, failures)


def _part_of(progress: Optional[Callable[[float, str], None]], low: float, high: float):
    """`progress` restricted to one stretch of the bar. Both halves report 0 -> 1 of their own
    work; handed the caller's callback unchanged, the bar would run full, jump back to zero and
    run full again."""
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
    result = run_core(zone, settings, out_dir, log, _part_of(progress, 0.0, CORE_SHARE),
                      should_cancel, cache_mode, client)
    return finish(project, result, meta, out_dir, log, _part_of(progress, CORE_SHARE, 1.0),
                  legends=legends, should_cancel=should_cancel, client=client, cache_mode=cache_mode,
                  pngs=pngs)
