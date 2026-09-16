"""One whole study - data, figures, maps, GeoPackage, project and PDF - without the QGIS GUI.

Run it with the Python of a QGIS installation, not with the plain venv:

  "C:\\Program Files\\QGIS 3.40.15\\bin\\python-qgis-ltr.bat" scripts\\run_headless.py \\
      --adres "Kortrijksesteenweg 100 Gent" --buffer 50 --out uitvoer\\gent
  python3 scripts/run_headless.py --x 104326 --y 192506 --buffer 50 --out uitvoer/gent

Afsluitcodes: 0 = volledig, 2 = geen bruikbare locatie (adres niet gevonden of niets opgegeven),
3 = klaar maar met gaten (een mislukt product of een bron die niet antwoordde).

Two things have to happen before anything else, and both are easy to miss.

*The font directory is set before the application starts.* The offscreen platform reads its fonts
from QT_QPA_FONTDIR and nowhere else; without it every letter renders as a black box while the
export still reports success. `compat.ensure_font_dir()` therefore runs before `QgsApplication`,
not after - Qt builds its font database when the application object is created.

*The application is GUI-enabled* (`QgsApplication([], True)`) although nothing shows a window:
rendering a layout goes through the QApplication machinery behind fonts, pixmaps and SVG, which a
GUI-less QgsApplication does not have. The offscreen platform keeps it headless anyway.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# Before the qgis import: the platform plugin is chosen when Qt is loaded, and a caller who set it
# themselves (a real display, a CI image with xvfb) keeps their choice.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from qgis.core import QgsApplication, QgsProject  # noqa: E402

from desktopstudie.core.logging_util import Log  # noqa: E402
from desktopstudie.core.report_content import ReportMeta  # noqa: E402
from desktopstudie.core.study import Settings  # noqa: E402
from desktopstudie.qgis import compat, pipeline  # noqa: E402
from scripts import _cli  # noqa: E402

NO_LOCATION = 2
INCOMPLETE = 3


def parse_args(argv=None) -> argparse.Namespace:
    ap = _cli.add_location_args(argparse.ArgumentParser(
        description="Volledige desktopstudie zonder QGIS-GUI: QGIS-project, GeoPackage en rapport.pdf."))
    ap.add_argument("--project", default="Desktopstudie", help="projectnaam op het titelblad")
    ap.add_argument("--projectnummer", default="", help="projectnummer op het titelblad")
    ap.add_argument("--auteur", default="", help="auteur op het titelblad en in de voettekst")
    ap.add_argument("--bedrijf", default="", help="bedrijf op het titelblad en in de voettekst")
    ap.add_argument("--logo", default="", help="pad naar een logo voor het titelblad")
    ap.add_argument("--geen-legendas", action="store_true",
                    help="geen aparte legendapagina's aanmaken; de quartairtekeningen worden wel "
                         "opgehaald, die zijn rapportinhoud")
    ap.add_argument("--paginas", action="store_true",
                    help="elk blad ook als PNG wegschrijven in paginas/ (rendert het rapport een "
                         "tweede keer)")
    args = ap.parse_args(argv)
    _cli.check_location(ap, args)
    return args


def run(args: argparse.Namespace, log: Log) -> int:
    out = Path(args.out)
    client = pipeline.make_client(out, log, args.cache)
    located = _cli.locate(args, client, log)
    if located is None:
        return NO_LOCATION
    zone = _cli.zone_of(args, *located)
    meta = ReportMeta(project=args.project, project_number=args.projectnummer, author=args.auteur,
                      company=args.bedrijf, logo_path=args.logo)
    settings = Settings(radius_m=args.straal)

    # The two halves are run separately rather than through `run_pipeline` for one reason: the
    # summary can then say where the time went. They share one client, so also one disk cache.
    started = time.monotonic()
    result = pipeline.run_core(zone, settings, out, log,
                               progress=pipeline.part_of(_print_progress, 0.0, pipeline.CORE_SHARE),
                               cache_mode=args.cache, client=client)
    core_done = time.monotonic()
    outcome = pipeline.finish(QgsProject.instance(), result, meta, out, log,
                              progress=pipeline.part_of(_print_progress, pipeline.CORE_SHARE, 1.0),
                              legends=not args.geen_legendas, client=client, cache_mode=args.cache,
                              pngs=args.paginas)
    finished = time.monotonic()

    failed = [p.source for p in outcome.result.provenance if not p.ok]
    pages = sum(len(chapter.pages) for chapter in outcome.report.chapters)
    print(f"pdf: {outcome.pdf}")
    print(f"project: {outcome.project_file}")
    print(f"geopackage: {outcome.geopackage}")
    print(f"pagina's: {pages} rapportpagina's, {len(outcome.page_pngs)} PNG's")
    print(f"duur: {finished - started:.0f} s totaal ({core_done - started:.0f} s kern, "
          f"{finished - core_done:.0f} s schil)")
    print(f"producten mislukt: {outcome.failures}")
    print(f"bronnen mislukt ({len(failed)}): {failed}")
    return INCOMPLETE if outcome.failures or failed else 0


def _print_progress(fraction: float, message: str) -> None:
    print(f"{fraction:5.0%} {message}")


def main(argv=None) -> int:
    args = parse_args(argv)
    # scope "qgis": this script drives the shell, and every child logger inherits the scope, so the
    # lines read the same as they do inside the plugin.
    log = Log("run_headless", sink=print, scope="qgis")
    compat.ensure_font_dir(log)  # before the application: Qt builds its font database there
    app = QgsApplication([], True)
    app.initQgis()
    try:
        return run(args, log)
    finally:
        app.exitQgis()


if __name__ == "__main__":
    sys.exit(main())
