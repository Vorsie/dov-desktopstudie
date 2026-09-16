"""Run the core end-to-end against the live services, without QGIS.

  python scripts/run_core.py --adres "Kortrijksesteenweg 100 Gent" --buffer 50 --out uitvoer/gent
  python scripts/run_core.py --x 104326 --y 192506 --buffer 50 --out uitvoer/gent

Afsluitcodes: 0 = volledig, 2 = adres niet gevonden, 3 = klaar maar met mislukte bronnen.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from desktopstudie.core import study  # noqa: E402
from desktopstudie.core.logging_util import Log  # noqa: E402
from desktopstudie.core.report_content import ReportMeta, build_report  # noqa: E402
from desktopstudie.core.services.http import study_client  # noqa: E402
from scripts import _cli  # noqa: E402


def main() -> int:
    ap = _cli.add_location_args(
        argparse.ArgumentParser(description="Desktopstudie-kern zonder QGIS: data, figuren en JSON."))
    args = ap.parse_args()
    _cli.check_location(ap, args)
    out = Path(args.out)
    log = Log("run_core", sink=print)
    client = study_client(out, log, args.cache)
    located = _cli.locate(args, client, log)
    if located is None:
        return 2
    zone = _cli.zone_of(args, *located)
    result = study.run(zone, study.Settings(radius_m=args.straal), client, out,
                       progress=lambda f, m: print(f"{f:5.0%} {m}"), log=log.child("study"))
    report = build_report(result, ReportMeta(project=zone.name, author="run_core", company="-"))
    failed = [p.source for p in result.provenance if not p.ok]
    print(f"hoofdstukken: {[c.title for c in report.chapters]}")
    print(f"figuren: {len(result.figures)}")
    print(f"signaleringen: {[s.code for s in result.signaleringen]}")
    print(f"bronnen mislukt: {failed}")
    # 0 = alles opgehaald, 2 = adres niet gevonden, 3 = studie klaar maar met gaten erin
    return 3 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
