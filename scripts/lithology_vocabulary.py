"""Tel de woorden in de lithologiebeschrijvingen van DOV, verspreid over Vlaanderen.

Dit is de analyse ACHTER `core/lithology.ORDINARY`: een eenmalige telling waaruit de lijst van
gewone woorden gecureerd is. De plugin draait dit nooit; een geotechnicus draait het opnieuw
wanneer DOV verandert of wanneer een streek te veel ruis geeft.

    python scripts/lithology_vocabulary.py                  # de hele telling
    python scripts/lithology_vocabulary.py --flags          # wat de huidige lijst zou vlaggen

Waarom meerdere punten: een woordenlijst gecureerd op één stad in zandig Vlaanderen kent de
polders niet (veen, schelpen, slappe klei), de leemstreek niet, de Kempense en Maaslandse grinden
niet en de Boomse klei niet. De punten hieronder dekken die settings; ze worden met de geocoder
van de plugin zelf opgezocht, zodat er geen coördinaten geraden worden.

De richting van de fout is met opzet de ongevaarlijke: de lijst bepaalt alleen wat GEWOON is en
dus onderdrukt wordt. Een woord dat er niet op staat, vlagt. Een onvolledige lijst levert dus ruis
op, nooit een gemiste rariteit - en dat mag nooit omgedraaid worden.
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from desktopstudie.core import parallel  # noqa: E402
from desktopstudie.core.geometry import buffer_point, polygon_wkt  # noqa: E402
from desktopstudie.core.lithology import is_ordinary, notable_terms  # noqa: E402
from desktopstudie.core.logging_util import Log  # noqa: E402
from desktopstudie.core.services import dov_xml  # noqa: E402
from desktopstudie.core.services.dov_wfs import DovWfs  # noqa: E402
from desktopstudie.core.services.geocoder import geocode  # noqa: E402
from desktopstudie.core.services.http import study_client  # noqa: E402

# De geologische settings van Vlaanderen, elk met een plaats die erin ligt. Namen in plaats van
# coördinaten: de geocoder van de plugin zoekt ze op, dus er wordt niets geraden.
PLACES = [
    ("kustpolders", "Oostende"),
    ("polders/veen", "Diksmuide"),
    ("kustvlakte", "Knokke-Heist"),
    ("zandig Vlaanderen", "Gent"),
    ("Scheldevallei", "Temse"),
    ("Boomse klei", "Boom"),
    ("leemstreek", "Sint-Truiden"),
    ("leemstreek/Haspengouw", "Tongeren"),
    ("Kempen", "Mol"),
    ("Kempen/Turnhout", "Turnhout"),
    ("Maasland", "Maaseik"),
    ("stedelijke ophoging", "Antwerpen"),
]
RADIUS_M = 1000.0
MAX_BOREHOLES = 60  # per punt; genoeg voor de woordenschat, niet zo veel dat DOV het merkt
WORD = re.compile(r"[^\W\d_]+", re.UNICODE)
CACHE = Path("uitvoer/woordenschat")


def _client(log: Log):
    return study_client(CACHE, log, "use")


def _descriptions(place: str, client, log: Log) -> List[Tuple[str, object]]:
    """(boringnummer, laag) voor de boringen rond één plaats."""
    hits = geocode(client, place, log=log)
    if not hits:
        print(f"  {place}: geen geocoderesultaat", file=sys.stderr)
        return []
    hit = hits[0]
    ring = buffer_point(hit.x, hit.y, RADIUS_M)
    wfs = DovWfs(client, log=log)
    features = wfs.within_distance("dov-pub:Boringen", polygon_wkt(ring), RADIUS_M, MAX_BOREHOLES)
    interpretations = wfs.interpretation_urls(polygon_wkt(ring), RADIUS_M, MAX_BOREHOLES)
    wanted = []
    for feature in features:
        props = feature["properties"]
        url = interpretations.get(props.get("fiche") or "")
        if url:
            wanted.append((props.get("boornummer") or "?", url))
    rows: List[Tuple[str, object]] = []

    def load(item) -> None:
        number, url = item
        for layer in dov_xml.parse_lithology(client.get(url + ".xml", timeout=20, retries=1)):
            rows.append((number, layer))

    failed = parallel.load_each(wanted, load, "lithologie", 4, log)
    # What did NOT come back matters as much as what did: a rerun that lost half its fetches to a
    # slow service reads exactly like the curation run unless the failures are on the page.
    print(f"  {place:22s} {hit.x:8.0f}/{hit.y:8.0f}  {len(features):3d} boringen, "
          f"{len(wanted):3d} met beschrijving, {len(rows):4d} lagen"
          + (f", {failed} MISLUKT" if failed else ""), file=sys.stderr)
    return rows


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--flags", action="store_true",
                        help="toon wat de huidige lijst zou vlaggen in plaats van de telling")
    args = parser.parse_args(argv)

    # A real sink, not a black hole: every warning the services raise belongs on stderr next to
    # the counts, so a rerun can be diffed against the curation run instead of merely trusted.
    log = Log("woordenschat", sink=lambda line: print(line, file=sys.stderr))
    client = _client(log)
    everything: List[Tuple[str, object]] = []
    print("punten:", file=sys.stderr)
    for setting, place in PLACES:
        rows = _descriptions(place, client, log)
        everything += [(f"{setting}/{number}", layer) for number, layer in rows]

    # The sample size and the date ride along with the table itself, so a rerun can be diffed
    # against the run the lists in `core/lithology` were curated from.
    sample = (f"{len(everything)} lagen uit {len({row[0] for row in everything})} boringen over "
              f"{len(PLACES)} punten, geteld op {datetime.now().strftime('%Y-%m-%d')}")
    print(f"\n{sample}", file=sys.stderr)

    if args.flags:
        print(f"# {sample}")
        per_borehole: Dict[str, list] = {}
        for number, layer in everything:
            per_borehole.setdefault(number, []).append(layer)
        flagged = Counter()
        with_flag = 0
        for layers in per_borehole.values():
            terms = notable_terms(layers)
            if terms:
                with_flag += 1
            for term in terms:
                flagged[term.word] += 1
        print(f"{with_flag}/{len(per_borehole)} boringen met een vlag, "
              f"{len(flagged)} verschillende woorden")
        for word, count in flagged.most_common():
            print(f"{count:5d}  {word}")
        return 0

    print(f"# {sample}")
    print("# De lijst bepaalt alleen wat GEWOON is; alles wat er niet op staat vlagt.")
    words = Counter()
    for _number, layer in everything:
        if layer.kind == "gecodeerd":
            continue
        words.update(word.lower() for word in WORD.findall(layer.description))
    print(f"{len(words)} verschillende woorden, {sum(words.values())} in totaal")
    print(f"{sum(1 for word in words if is_ordinary(word))} daarvan staan nu als gewoon genoteerd")
    for word, count in words.most_common():
        print(f"{count:6d}  {'gewoon' if is_ordinary(word) else 'VLAG  '}  {word}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
