"""What the two command-line runners share: how a location is asked for and how it is resolved.

`run_core.py` and `run_headless.py` take the same study from opposite ends - one stops after the
data, the other goes on to the PDF - but the front of both is identical: the same four ways to say
where, the same refusal to study "somewhere", and the same zone built from the answer. Written
twice, the two would drift the day one of them gains an option.

Only the exit codes stay in the scripts themselves: what a missing address costs is the caller's
decision, not this module's.
"""
from __future__ import annotations

import argparse
from typing import Optional, Tuple

from desktopstudie.core import geometry
from desktopstudie.core.logging_util import Log
from desktopstudie.core.model import StudyZone
from desktopstudie.core.services.geocoder import geocode
from desktopstudie.core.services.http import CACHE_MODES, HttpClient


def add_location_args(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    """The options that say WHERE and HOW WIDE, plus the output directory and the cache mode."""
    parser.add_argument("--adres", help="adres om te geocoderen; anders --x/--y")
    parser.add_argument("--x", type=float, help="X in Lambert 72 (EPSG:31370)")
    parser.add_argument("--y", type=float, help="Y in Lambert 72 (EPSG:31370)")
    parser.add_argument("--buffer", type=float, default=50.0,
                        help="straal van de zonecirkel rond het punt (m)")
    parser.add_argument("--straal", type=float, default=500.0,
                        help="zoekstraal voor sonderingen/boringen/peilputten (m)")
    parser.add_argument("--cache", choices=CACHE_MODES, default="use",
                        help="use: schijfcache gebruiken; refresh: opnieuw ophalen; off: geen cache")
    parser.add_argument("--out", required=True, help="uitvoermap")
    return parser


def check_location(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    """Refuse what cannot mean one place, before anything is fetched or created on disk.

    Both an address and a coordinate is ambiguous; neither is no location at all. Argparse ends
    the run with code 2 for both - the same code the scripts use for "address not found", because
    to the caller they are the same answer: there is nowhere to study.
    """
    if args.adres and (args.x is not None or args.y is not None):
        parser.error("geef --adres OF --x/--y, niet allebei")
    if not args.adres and (args.x is None or args.y is None):
        parser.error("geef --adres of zowel --x als --y")


def locate(args: argparse.Namespace, client: HttpClient,
           log: Log) -> Optional[Tuple[float, float, Optional[str]]]:
    """(x, y, address) for the zone, or None when the address could not be found.

    `check_location` has already refused a call without a location, so the only way to end up
    nowhere here is a geocoder that does not know the address.
    """
    if args.adres:
        hits = geocode(client, args.adres, log=log.child("geocoder"))
        if not hits:
            log.error(f"adres niet gevonden: {args.adres}")
            return None
        return hits[0].x, hits[0].y, hits[0].address
    return args.x, args.y, None


def zone_of(args: argparse.Namespace, x: float, y: float, address: Optional[str]) -> StudyZone:
    """The circular study zone around the located point, named after the address when there is one."""
    return StudyZone(ring=geometry.buffer_point(x, y, args.buffer),
                     name=address or f"{x:.0f}/{y:.0f}", radius_m=args.straal, address=address)
