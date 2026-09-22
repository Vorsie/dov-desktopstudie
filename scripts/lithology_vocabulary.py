"""Count the words in DOV's lithology descriptions, spread over Flanders.

This is the analysis BEHIND `core/lithology.ORDINARY`: a one-off count the list of plain words was
curated from. The plugin never runs it; a geotechnician runs it again when DOV changes or when one
region produces too much noise.

    python scripts/lithology_vocabulary.py                  # the whole count
    python scripts/lithology_vocabulary.py --flags          # what the current list would flag

Why several points: a vocabulary curated on one city in sandy Flanders does not know the polders
(veen, schelpen, slappe klei), nor the loam belt, nor the Kempen and Maasland gravels, nor the
Boom clay. The points below cover those settings; they are looked up with the plugin's own
geocoder, so no coordinates are guessed.

The direction of the error is deliberately the harmless one: the list only decides what is PLAIN
and therefore suppressed. A word that is not on it flags. An incomplete list yields noise, never a
missed oddity - and that may never be turned around.
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

# The geological settings of Flanders, each with a place that lies in it. Names rather than
# coordinates: the plugin's geocoder looks them up, so nothing is guessed.
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
MAX_BOREHOLES = 60  # per point; enough for the vocabulary, not so many that DOV notices
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
