"""Run studies at random places in Flanders and let the machine say what goes wrong.

Everything rendered so far was the same zone in Gent, and the two bug reports that mattered most
came from a user looking somewhere else. This tool picks a place itself, runs a whole study there
and then checks the result, so that what comes out is "look at run 2, sheet 31" instead of a stack
of PDFs to leaf through.

    "C:\\Program Files\\QGIS 3.40.15\\bin\\python-qgis-ltr.bat" scripts/random_study.py --aantal 3
    python3 scripts/random_study.py --aantal 1 --seed 12345

A script of its own rather than a `--willekeurig` on `run_headless.py`: that is a tool that runs
ONE study and reports on it, this is one that runs several and then INSPECTS them. That inspection
is the half with the value in it, and it does not belong in the ordinary loop.

Developer tooling: it is not in the zip and it may take minutes per run.

The network is not a bug. DOV and the portal stutter, and a source that did not answer is a
different thing from a source that answered and was handled wrongly by us. Those two are kept
apart in the report, and a run with nothing but stutters succeeds.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from qgis.core import QgsApplication, QgsProject  # noqa: E402

from desktopstudie.core import catalogue, geometry, lithology  # noqa: E402
from desktopstudie.core.logging_util import Log  # noqa: E402
from desktopstudie.core.model import StudyZone  # noqa: E402
from desktopstudie.core.report_content import ReportMeta  # noqa: E402
from desktopstudie.core.services.http import CACHE_MODES, DATA_DIR  # noqa: E402
from desktopstudie.core.study import Settings  # noqa: E402
from desktopstudie.qgis import compat, pipeline  # noqa: E402
from desktopstudie.qgis.prefetch import MAP_IMAGE_DIR  # noqa: E402

# The envelope of Flanders in Lambert 72, taken generously. Inside this box lie the Netherlands,
# Wallonia and the North Sea too, so every point is checked against the municipal borders before
# it counts.
FLANDERS_BOX = (22000.0, 155000.0, 258000.0, 244000.0)
BOUNDARY_WFS = "https://geo.api.vlaanderen.be/VRBG/wfs"
BOUNDARY_LAYER, BOUNDARY_GEOM, BOUNDARY_NAME = "VRBG:Refgem", "SHAPE", "NAAM"
MAX_TRIES = 200
BLANK_SHEET = 0.02  # a sheet under two per cent ink is empty in practice
# How many flagged terms may stand under one borehole before the line becomes unreadable. No list
# of "noise words" of its own beside it: `lithology.ORDINARY` says what is PLAIN, and a second
# list of what is NOT plain turns around exactly the direction that is forbidden there.
MAX_REMARK_TERMS = 6


@dataclass
class Findings:
    """What stood out about a run, split into what we got wrong and what the network did."""

    ours: List[str] = field(default_factory=list)
    network: List[str] = field(default_factory=list)

    def ok(self) -> bool:
        return not self.ours


def _municipality(client, x: float, y: float, log: Log) -> Optional[str]:
    """The Flemish municipality this point lies in, or None. The border decides, not a box."""
    params = {"service": "WFS", "version": "2.0.0", "request": "GetFeature",
              "typeNames": BOUNDARY_LAYER, "outputFormat": "application/json",
              "srsName": "EPSG:31370",
              "CQL_FILTER": f"INTERSECTS({BOUNDARY_GEOM},POINT({x} {y}))", "count": "1"}
    url = BOUNDARY_WFS + "?" + urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
    try:
        doc = json.loads(client.get(url, timeout=40, retries=1))
    except Exception as exc:  # noqa: BLE001 - a stutter here is not a bug in the study
        log.warning(f"gemeentegrens niet bevraagd: {type(exc).__name__}: {exc}")
        return None
    feats = doc.get("features", [])
    return feats[0]["properties"].get(BOUNDARY_NAME) if feats else None


def pick_point(rng: random.Random, client, log: Log) -> Tuple[float, float, str]:
    """A uniformly distributed point INSIDE Flanders, not inside a box around it."""
    minx, miny, maxx, maxy = FLANDERS_BOX
    for _ in range(MAX_TRIES):
        x, y = rng.uniform(minx, maxx), rng.uniform(miny, maxy)
        name = _municipality(client, x, y, log)
        if name:
            return round(x, 1), round(y, 1), name
    raise SystemExit("geen punt in Vlaanderen gevonden; ligt de grenzendienst plat?")


def _ink(path: Path) -> float:
    import numpy as np
    from PIL import Image

    grey = np.array(Image.open(path).convert("L"))
    return float((grey < 245).mean())


def _uniform(path: Path) -> bool:
    import numpy as np
    from PIL import Image

    arr = np.array(Image.open(path).convert("RGB"))
    return bool((arr == arr[0, 0]).all())


def _page_titles(report, sheets: int) -> Dict[int, str]:
    """Sheet number -> title, but only while those two run one to one.

    A report page is not the same thing as a sheet: a long table runs on over several sheets and
    two short pieces share one. The moment those counts differ the mapping no longer holds, and a
    wrong title beside a sheet number is worse than no title - the reader then looks in the wrong
    place. So rather say nothing than invent something.
    """
    pages = [f"{chapter.number}. {chapter.title} - {page.title}"
             for chapter in report.chapters for page in chapter.pages]
    if len(pages) != sheets:
        return {}
    return {number: title for number, title in enumerate(pages, start=1)}


def _map_image(out: Path, map_id: str) -> Optional[Path]:
    hits = sorted((out / DATA_DIR / MAP_IMAGE_DIR).glob(f"{map_id}_*.png"))
    return hits[0] if hits else None


def inspect(run: int, where: str, out: Path, outcome, _log: Log) -> Findings:
    """Everything a human would otherwise have to check by hand."""
    found = Findings()
    for prov in outcome.result.provenance:
        if not prov.ok:
            found.network.append(f"run {run} {where}: bron gaf niets - {prov.source}")
    for failure in outcome.failures:
        found.ours.append(f"run {run} {where}: product mislukt - {failure}")

    titles = _page_titles(outcome.report, outcome.sheets)
    # The sheets as the pipeline delivers them: already sorted by page number, so the place in the
    # list IS the sheet number and the folder name need not be spelled out again here.
    for number, png in enumerate(outcome.page_pngs, start=1):
        share = _ink(png)
        if share < BLANK_SHEET:
            title = titles.get(number)
            found.ours.append(f"run {run} {where}: blad {number} is {share:.1%} inkt"
                              + (f" - {title}" if title else ""))

    # The two cases that bit us this week, both machine-visible: a map that draws something but
    # yields no fact row, and a remark line drowning in noise.
    for fact in outcome.result.map_facts:
        entry = catalogue.by_id(fact.map_id)
        # A map WITH a backdrop is never uniform - the base map is always under it - so this test
        # says nothing there and keeps quiet rather than pointing at every empty map.
        if fact.rows or entry is None or entry.backdrop:
            continue
        image = _map_image(out, fact.map_id)
        if image is not None and not _uniform(image):
            found.ours.append(f"run {run} {where}: kaart {fact.map_id} tekent wel iets maar "
                              f"levert geen enkele feitenrij")
    # Counted on the terms the vocabulary itself flags, not on the Dutch sentence the signalering
    # writes around them: rewrite that sentence and this rule would quietly stop firing while the
    # script reports "in orde".
    for borehole in outcome.result.boreholes:
        terms = lithology.notable_terms(borehole.lithology)
        if len(terms) > MAX_REMARK_TERMS:
            found.ours.append(f"run {run} {where}: opmerkingsregel met {len(terms)} termen - "
                              f"boring {borehole.number}")
    return found


def one_run(run: int, rng: random.Random, args, log: Log) -> Findings:
    out = Path(args.out) / f"run{run}"
    client = pipeline.make_client(out, log, args.cache)
    x, y, town = pick_point(rng, client, log)
    where = f"{x:.0f}/{y:.0f} ({town})"
    print(f"\n=== run {run}: {where} ===", flush=True)
    zone = StudyZone(ring=geometry.buffer_point(x, y, args.buffer),
                     name=f"Willekeurig {town}", radius_m=args.straal)
    meta = ReportMeta(project=f"Willekeurig {town}", author="random_study", company="test")
    try:
        result = pipeline.run_core(zone, Settings(radius_m=args.straal), out, log,
                                   cache_mode=args.cache, client=client)
        outcome = pipeline.finish(QgsProject.instance(), result, meta, out, log,
                                  client=client, cache_mode=args.cache, pngs=True,
                                  study_groups=False)
    except Exception as exc:  # noqa: BLE001 - het afbreken zelf is de bevinding
        found = Findings()
        found.ours.append(f"run {run} {where}: de studie brak af - {type(exc).__name__}: {exc}")
        return found
    found = inspect(run, where, out, outcome, log)
    print(f"--- run {run}: {outcome.sheets} bladen, {len(found.ours)} bevinding(en), "
          f"{len(found.network)} hapering(en)", flush=True)
    return found


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--aantal", type=int, default=3, help="hoeveel plaatsen (standaard 3)")
    ap.add_argument("--seed", type=int, default=None, help="om een reeks exact te herhalen")
    ap.add_argument("--out", default="uitvoer/willekeurig", help="map voor de runs")
    ap.add_argument("--buffer", type=float, default=50.0, help="straal van de zone in meter")
    ap.add_argument("--straal", type=float, default=500.0, help="zoekstraal in meter")
    ap.add_argument("--cache", default=CACHE_MODES[0], choices=CACHE_MODES)
    args = ap.parse_args(argv)

    seed = args.seed if args.seed is not None else random.randrange(1_000_000)
    print(f"seed {seed} - herhaal deze reeks met --seed {seed}")
    rng = random.Random(seed)

    compat.ensure_font_dir()
    app = QgsApplication([], True)
    app.initQgis()
    # To stderr, so the report on stdout stays clean: a tool that takes minutes per run and throws
    # every log line away leaves no way to trace a stutter afterwards.
    log = Log("willekeurig", sink=lambda line: print(line, file=sys.stderr), scope="qgis")
    try:
        all_found = [one_run(run, rng, args, log) for run in range(1, args.aantal + 1)]
    finally:
        app.exitQgis()

    print("\n=== bevindingen ===")
    for found in all_found:
        for line in found.ours:
            print(f"  {line}")
    print("\n=== haperingen (geen bug bij ons) ===")
    for found in all_found:
        for line in found.network:
            print(f"  {line}")
    print("\n=== oordeel ===")
    for run, found in enumerate(all_found, start=1):
        print(f"  run {run}: {'in orde' if found.ok() else f'{len(found.ours)} bevinding(en)'}")
    return 0 if all(found.ok() for found in all_found) else 1


if __name__ == "__main__":
    sys.exit(main())
