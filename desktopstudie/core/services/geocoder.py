"""Geopunt geolocation v4: address text -> candidates with Lambert 72 coordinates."""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from ..catalogue import GEOCODER_URL
from ..logging_util import Log


@dataclass
class GeocodeHit:
    address: str
    x: float
    y: float
    municipality: str
    postcode: str
    location_type: str

    @property
    def is_precise(self) -> bool:
        return self.location_type.startswith("basisregisters_huisnummer")


# How many candidates to ask for: the dialog shows a short list and the scripts take the first.
MAX_RESULTS = 5


def geocode(client, query: str, log: Optional[Log] = None) -> List[GeocodeHit]:
    """Candidates for `query`, best first. An address the geocoder does not know answers HTTP 200
    with an empty LocationResult, so "no candidates" is WARNED about with the query in it rather
    than handed back as a bare empty list."""
    payload = client.get_json(GEOCODER_URL, {"q": query, "c": MAX_RESULTS})
    hits: List[GeocodeHit] = []
    for item in payload.get("LocationResult", []):
        loc = item.get("Location", {})
        if "X_Lambert72" not in loc or "Y_Lambert72" not in loc:
            continue
        hits.append(GeocodeHit(
            address=item.get("FormattedAddress", ""),
            x=float(loc["X_Lambert72"]),
            y=float(loc["Y_Lambert72"]),
            municipality=item.get("Municipality", ""),
            postcode=item.get("Zipcode", ""),
            location_type=item.get("LocationType", ""),
        ))
    if not hits and log:
        log.warning(f"geocoder: geen kandidaat gevonden voor {query!r}")
    return hits
