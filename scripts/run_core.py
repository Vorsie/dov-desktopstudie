"""Run the core end-to-end against the live services, without QGIS.

  python scripts/run_core.py --adres "Kortrijksesteenweg 100 Gent" --buffer 50 --out uitvoer/gent
  python scripts/run_core.py --x 104326 --y 192506 --buffer 50 --out uitvoer/gent
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from desktopstudie.core import geometry, study  # noqa: E402
from desktopstudie.core.logging_util import Log  # noqa: E402
from desktopstudie.core.model import StudyZone  # noqa: E402
from desktopstudie.core.report_content import ReportMeta, build_report  # noqa: E402
from desktopstudie.core.services.geocoder import geocode  # noqa: E402
from desktopstudie.core.services.http import CACHE_MODES, HttpClient  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Desktopstudie-kern zonder QGIS: data, figuren en JSON.")
    ap.add_argument("--adres", help="adres om te geocoderen; anders --x/--y")
    ap.add_argument("--x", type=float, help="X in Lambert 72 (EPSG:31370)")
    ap.add_argument("--y", type=float, help="Y in Lambert 72 (EPSG:31370)")
    ap.add_argument("--buffer", type=float, default=50.0, help="straal van de zonecirkel rond het punt (m)")
    ap.add_argument("--straal", type=float, default=500.0, help="zoekstraal voor sonderingen/boringen/peilputten (m)")
    ap.add_argument("--cache", choices=CACHE_MODES, default="use",
                    help="use: schijfcache gebruiken; refresh: opnieuw ophalen en cache bijwerken; off: geen cache")
    ap.add_argument("--out", required=True, help="uitvoermap (krijgt data/ en figuren/)")
    args = ap.parse_args()
    if not args.adres and (args.x is None or args.y is None):
        ap.error("geef --adres of zowel --x als --y")
    out = Path(args.out)
    log = Log("run_core", sink=print)
    client = HttpClient(cache_dir=out / "data" / "cache", cache_mode=args.cache, log=log.child("http"))
    address = None
    if args.adres:
        hits = geocode(client, args.adres)
        if not hits:
            log.error(f"adres niet gevonden: {args.adres}")
            print("adres niet gevonden")
            return 2
        x, y, address = hits[0].x, hits[0].y, hits[0].address
    else:
        x, y = args.x, args.y
    zone = StudyZone(ring=geometry.buffer_point(x, y, args.buffer), name=address or f"{x:.0f}/{y:.0f}",
                     radius_m=args.straal, address=address)
    result = study.run(zone, study.Settings(radius_m=args.straal), client, out,
                       progress=lambda f, m: print(f"{f:5.0%} {m}"), log=log)
    report = build_report(result, ReportMeta(project=zone.name, author="run_core", company="-"))
    print(f"hoofdstukken: {[c.title for c in report.chapters]}")
    print(f"figuren: {len(result.figures)}")
    print(f"signaleringen: {[s.code for s in result.signaleringen]}")
    print(f"bronnen mislukt: {[p.source for p in result.provenance if not p.ok]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
