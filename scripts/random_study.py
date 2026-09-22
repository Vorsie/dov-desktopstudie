"""Draai studies op willekeurige plaatsen in Vlaanderen en laat de machine zeggen wat er misgaat.

Alles wat we tot nu toe renderden was dezelfde zone in Gent, en de twee bugmeldingen die er het
meest toe deden kwamen van een gebruiker die ergens anders keek. Dit gereedschap kiest zelf een
plek, draait er een volledige studie en controleert daarna het resultaat, zodat er "kijk naar run
2, blad 31" uit komt in plaats van een stapel PDF's om door te bladeren.

    "C:\\Program Files\\QGIS 3.40.15\\bin\\python-qgis-ltr.bat" scripts/random_study.py --aantal 3
    python3 scripts/random_study.py --aantal 1 --seed 12345

Een eigen script en geen `--willekeurig` op `run_headless.py`: dat is een gereedschap dat EEN
studie draait en erover rapporteert, dit is er een dat er meerdere draait en ze daarna NAKIJKT.
Die controle is de helft die waarde heeft, en ze hoort niet in de gewone loop thuis.

Ontwikkelaarsgereedschap: het zit niet in de zip en het mag minuten per run duren.

Het netwerk is geen bug. DOV en het portaal haperen, en een bron die niet antwoordde is iets
anders dan een bron die antwoordde en door ons verkeerd behandeld werd. Die twee staan apart in
het verslag, en een run met alleen haperingen slaagt.
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

# De omhullende van Vlaanderen in Lambert 72, ruim genomen. Binnen deze doos ligt ook Nederland,
# Wallonie en de Noordzee, dus elk punt wordt bij de gemeentegrenzen nagevraagd voor het telt.
FLANDERS_BOX = (22000.0, 155000.0, 258000.0, 244000.0)
BOUNDARY_WFS = "https://geo.api.vlaanderen.be/VRBG/wfs"
BOUNDARY_LAYER, BOUNDARY_GEOM, BOUNDARY_NAME = "VRBG:Refgem", "SHAPE", "NAAM"
MAX_TRIES = 200
BLANK_SHEET = 0.02  # een blad onder twee procent inkt is in de praktijk leeg
# Hoeveel gevlagde termen er onder een boring mogen staan voor de regel onleesbaar wordt. Geen
# eigen lijst van "ruiswoorden" ernaast: `lithology.ORDINARY` zegt wat GEWOON is, en een tweede
# lijst van wat NIET gewoon is draait precies de richting om die daar verboden is.
MAX_REMARK_TERMS = 6


@dataclass
class Findings:
    """Wat er aan een run opviel, gescheiden in wat wij fout deden en wat het netwerk deed."""

    ours: List[str] = field(default_factory=list)
    network: List[str] = field(default_factory=list)

    def ok(self) -> bool:
        return not self.ours


def _municipality(client, x: float, y: float, log: Log) -> Optional[str]:
    """De Vlaamse gemeente waarin dit punt ligt, of None. De grens beslist, niet een doos."""
    params = {"service": "WFS", "version": "2.0.0", "request": "GetFeature",
              "typeNames": BOUNDARY_LAYER, "outputFormat": "application/json",
              "srsName": "EPSG:31370",
              "CQL_FILTER": f"INTERSECTS({BOUNDARY_GEOM},POINT({x} {y}))", "count": "1"}
    url = BOUNDARY_WFS + "?" + urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
    try:
        doc = json.loads(client.get(url, timeout=40, retries=1))
    except Exception as exc:  # noqa: BLE001 - een hapering hier is geen bug in de studie
        log.warning(f"gemeentegrens niet bevraagd: {type(exc).__name__}: {exc}")
        return None
    feats = doc.get("features", [])
    return feats[0]["properties"].get(BOUNDARY_NAME) if feats else None


def pick_point(rng: random.Random, client, log: Log) -> Tuple[float, float, str]:
    """Een gelijkmatig verdeeld punt BINNEN Vlaanderen, niet binnen een doos eromheen."""
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
    """Bladnummer -> titel, maar alleen als die twee een op een lopen.

    Een rapportpagina is niet hetzelfde als een blad: een lange tabel loopt door over meerdere
    bladen en twee korte stukken delen er een. Zodra die aantallen verschillen klopt de toewijzing
    niet meer, en een verkeerde titel bij een bladnummer is erger dan geen titel - dan zoekt de
    lezer op de verkeerde plaats. Dus liever niets zeggen dan iets verzinnen.
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
    """Alles wat een mens anders met de hand zou moeten nakijken."""
    found = Findings()
    for prov in outcome.result.provenance:
        if not prov.ok:
            found.network.append(f"run {run} {where}: bron gaf niets - {prov.source}")
    for failure in outcome.failures:
        found.ours.append(f"run {run} {where}: product mislukt - {failure}")

    titles = _page_titles(outcome.report, outcome.sheets)
    # De bladen zoals de pijplijn ze aflevert: al op paginanummer gesorteerd, dus de plaats in de
    # lijst IS het bladnummer en de mapnaam hoeft hier niet nog eens gespeld te worden.
    for number, png in enumerate(outcome.page_pngs, start=1):
        share = _ink(png)
        if share < BLANK_SHEET:
            title = titles.get(number)
            found.ours.append(f"run {run} {where}: blad {number} is {share:.1%} inkt"
                              + (f" - {title}" if title else ""))

    # De twee gevallen die ons deze week beten, allebei machinaal te zien: een kaart die wel iets
    # tekent maar geen feiten oplevert, en een opmerkingsregel die in ruis verzuipt.
    for fact in outcome.result.map_facts:
        entry = catalogue.by_id(fact.map_id)
        # Een kaart MET ondergrond is nooit uniform - de basiskaart staat er altijd onder - dus
        # daarop zegt deze proef niets en zwijgt ze liever dan elke lege kaart aan te wijzen.
        if fact.rows or entry is None or entry.backdrop:
            continue
        image = _map_image(out, fact.map_id)
        if image is not None and not _uniform(image):
            found.ours.append(f"run {run} {where}: kaart {fact.map_id} tekent wel iets maar "
                              f"levert geen enkele feitenrij")
    # Geteld op de termen die de woordenlijst zelf vlagt, niet op de Nederlandse zin die de
    # signalering eromheen schrijft: wie die zin herschrijft, legt anders stilzwijgend deze regel
    # plat en het script meldt "in orde".
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
    # Naar stderr, zodat het verslag op stdout schoon blijft: een gereedschap dat een run van
    # minuten doet en elke logregel weggooit, laat een hapering niet meer terugzoeken.
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
