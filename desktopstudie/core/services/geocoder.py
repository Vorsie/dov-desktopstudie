"""Geopunt geolocation v4: address text -> candidates with Lambert 72 coordinates."""
from __future__ import annotations

from dataclasses import dataclass
from typing import List

from ..catalogue import GEOCODER_URL


@dataclass
class GeocodeHit:
    address: str
    x: float
    y: float
    municipality: str
    postcode: str
    location_type: str


def geocode(client, query: str, max_results: int = 5) -> List[GeocodeHit]:
    payload = client.get_json(GEOCODER_URL, {"q": query, "c": max_results})
    hits: List[GeocodeHit] = []
    for item in payload.get("LocationResult", []):
        loc = item.get("Location", {})
        if "X_Lambert72" not in loc:
            continue
        hits.append(GeocodeHit(
            address=item.get("FormattedAddress", ""),
            x=float(loc["X_Lambert72"]),
            y=float(loc["Y_Lambert72"]),
            municipality=item.get("Municipality", ""),
            postcode=item.get("Zipcode", ""),
            location_type=item.get("LocationType", ""),
        ))
    return hits
