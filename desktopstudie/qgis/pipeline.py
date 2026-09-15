"""One study end to end: core run -> relief -> checks -> report -> layers -> layout -> exports.

Split in two on purpose. `run_core` is everything that only needs Python and the network, so it
can run on a worker thread (the plugin's QgsTask); `finish` is everything that touches QGIS map
layers, a layout and a project, which has to happen on the main thread. `run_pipeline` is the two
of them for a caller that has no threads to worry about - the headless script.

Three things are easy to get wrong here and are therefore done in one place.

*The rules run twice.* The core already filled `signaleringen`, but the relief only arrives here,
and the relief rule cannot fire without it. So `checks.run_all` runs again over the completed
result - and the two signals the orchestrator alone could know (a truncated WFS list, failed
doorprik points) are carried over, because nothing in the data can rebuild them.

*The open project is not the deliverable.* The study's groups go into the project the user has
open, but the `.qgz` next to the PDF is a FRESH project built from the GeoPackage, so the file
still works weeks later, on another machine, without this session.

*Offscreen renders without fonts.* Before the first page is drawn the font directory is secured
(see `compat.ensure_font_dir`); otherwise every letter comes out of the export as a black box
while every check stays green.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional

from qgis.core import QgsMapLayer, QgsProject

from ..core import catalogue, checks
from ..core.logging_util import Log
from ..core.model import StudyResult, StudyZone
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
# How much of a whole run the core half is worth on the progress bar. Roughly right for a study
# of a few hundred fiches; the point is only that the bar keeps moving forward.
CORE_SHARE = 0.5


@dataclass
class PipelineResult:
    result: StudyResult
    report: Report
    pdf: Path
    project_file: Path
    geopackage: Path
    page_pngs: List[Path]


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


def _stop_if_cancelled(should_cancel: Optional[Callable[[], bool]]) -> None:
    if should_cancel is not None and should_cancel():
        raise StudyCancelled("afgebroken door de gebruiker")


def _study_overlays(result: StudyResult) -> Dict[str, List[QgsMapLayer]]:
    """The layers a map page can ask to draw on top of a catalogue map."""
    return {"zone": [layers.zone_layer(result.zone)],
            "section": [layers.line_layer(result.zone)],
            "investigations": [layers.points_layer("sondering", result.cpts),
                               layers.points_layer("boring", result.boreholes),
                               layers.points_layer("peilput", result.gw_filters),
                               layers.circle_layer(result.zone)]}


def _map_layers_into_groups(project: QgsProject, log: Log) -> Dict[str, List[QgsMapLayer]]:
    """Load every catalogue map as a WMS layer, group it in the project and index it by map id.

    A layer that does not come back valid (an unreachable service) costs its own map page, not the
    report: it is logged and left out, and the page then shows the overlays on an empty ground.
    """
    layers_by_map: Dict[str, List[QgsMapLayer]] = {}
    for chapter, title in CHAPTER_GROUPS.items():
        group_layers: List[QgsMapLayer] = []
        for entry in catalogue.entries(chapter):
            layer = layers.wms_layer(entry)
            if not layer.isValid():
                log.warning(f"WMS-laag niet geldig: {entry.id} ({entry.wms_url})")
                continue
            layers_by_map[entry.id] = [layer]
            group_layers.append(layer)
        layers.add_group(project, title, group_layers, visible=False)
        log.info(f"{title}: {len(group_layers)} van {len(catalogue.entries(chapter))} kaarten geladen")
    return layers_by_map


def _install_layout(project: QgsProject, lay) -> None:
    """Hand the layout to the project's layout manager, replacing the one from an earlier run.

    Two layouts of the same name in one manager leave the user picking blind, and the manager
    takes ownership - after this the project keeps the layout alive, not us.
    """
    manager = project.layoutManager()
    existing = manager.layoutByName(layout_mod.LAYOUT_NAME)
    if existing is not None:
        manager.removeLayout(existing)
    manager.addLayout(lay)


def finish(project: QgsProject, result: StudyResult, meta: ReportMeta, out_dir, log: Log,
           progress: Optional[Callable[[float, str], None]] = None, legends: bool = True,
           should_cancel: Optional[Callable[[], bool]] = None,
           client: Optional[HttpClient] = None, cache_mode: str = "use") -> PipelineResult:
    """Main-thread part: relief, checks, report, layers, layout, exports.

    `project` is the project the layers and the layout go into - the one the user has open in the
    plugin, a fresh one headless. The standalone `.qgz` is built separately, from the GeoPackage.
    """
    out_dir = Path(out_dir)
    report_progress = progress or (lambda fraction, message: None)
    compat.ensure_font_dir(log)

    _stop_if_cancelled(should_cancel)
    report_progress(0.05, "Relief uit DHMV")
    result.relief = dem.relief_of_zone(layers.zone_layer(result.zone), log.child("dem"), should_cancel)
    _stop_if_cancelled(should_cancel)
    # The rules again now that the relief is in; see the module docstring for the two signals that
    # are carried over rather than recomputed.
    result.signaleringen = checks.validate(checks.run_all(result) + orchestrator_signals(result))
    json_path = out_dir / DATA_DIR / JSON_NAME
    json_path.parent.mkdir(parents=True, exist_ok=True)
    result.write_json(json_path)
    report = build_report(result, meta)
    log.info(f"Rapport: {len(report.chapters)} hoofdstukken, "
             f"{sum(len(chapter.pages) for chapter in report.chapters)} pagina's")

    report_progress(0.15, "Lagen")
    overlays = _study_overlays(result)
    layers_by_map = _map_layers_into_groups(project, log)
    layers.add_group(project, layers.ZONE_GROUP, overlays["zone"] + overlays["section"])
    layers.add_group(project, layers.INVESTIGATION_GROUP, overlays["investigations"])

    _stop_if_cancelled(should_cancel)
    legend_images: Dict[str, Path] = {}
    if legends:
        report_progress(0.30, "Legendas")
        # prepare_legends picks the entries that ask for a legend itself; it re-uses the study's
        # HTTP cache, so a second run in the same output directory fetches nothing.
        legend_images = layout_mod.prepare_legends(catalogue.entries(), out_dir,
                                                   client or make_client(out_dir, log, cache_mode),
                                                   log.child("legendas"))

    _stop_if_cancelled(should_cancel)
    report_progress(0.40, "Layout")
    lay = layout_mod.build_layout(project, report, layers_by_map, overlays, out_dir, result.zone.ring,
                                  report.meta, legends=legends, legend_images=legend_images)
    _install_layout(project, lay)
    log.info(f"Layout: {lay.pageCollection().pageCount()} bladen")

    _stop_if_cancelled(should_cancel)
    report_progress(0.55, "PDF")
    pdf = export.export_pdf(lay, out_dir / PDF_NAME)
    report_progress(0.80, "Pagina's als PNG")
    pngs = export.export_pages_png(lay, out_dir / PAGES_DIR)

    report_progress(0.90, "GeoPackage")
    gpkg = out_dir / DATA_DIR / GPKG_NAME
    gpkg.parent.mkdir(parents=True, exist_ok=True)  # OGR creates the file, never the folder
    layers.write_geopackage(overlays["zone"] + overlays["section"] + overlays["investigations"], gpkg,
                            project.transformContext())
    report_progress(0.95, "Projectbestand")
    project_file = export.write_project(layers.standalone_project(gpkg, CHAPTER_GROUPS, log),
                                        out_dir / PROJECT_NAME)
    report_progress(1.0, "Klaar")
    log.info(f"Klaar: {pdf.name} ({len(pngs)} bladen), {project_file.name}, {gpkg.name} in {out_dir}")
    return PipelineResult(result, report, pdf, project_file, gpkg, pngs)


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
                 legends: bool = True) -> PipelineResult:
    """One study from zone to PDF, on the calling thread. The client is made once so both halves
    share the same disk cache."""
    out_dir = Path(out_dir)
    client = make_client(out_dir, log, cache_mode)
    result = run_core(zone, settings, out_dir, log, _part_of(progress, 0.0, CORE_SHARE),
                      should_cancel, cache_mode, client)
    return finish(project, result, meta, out_dir, log, _part_of(progress, CORE_SHARE, 1.0),
                  legends=legends, should_cancel=should_cancel, client=client, cache_mode=cache_mode)
