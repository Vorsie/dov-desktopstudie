"""DOV WFS 2.0.0 access. Rules learned from the live service: never send BBOX together with
CQL_FILTER (fold spatial predicates into CQL); at most 500 features per response, so page with
startIndex/count; the geometry attribute name differs per layer (geom/shape/geometry/the_geom),
so look it up with DescribeFeatureType once per layer."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from ..catalogue import DOV_WFS_URL

Feature = Dict[str, Any]


def feature_xy(feature: Feature) -> Tuple[float, float]:
    coords = feature["geometry"]["coordinates"]
    return float(coords[0]), float(coords[1])


class DovWfs:
    def __init__(self, client, url: str = DOV_WFS_URL, page_size: int = 500):
        self.client = client
        self.url = url
        self.page_size = page_size
        self._geom_cache: Dict[str, str] = {}

    def geometry_field(self, typename: str) -> str:
        if typename not in self._geom_cache:
            payload = self.client.get_json(self.url, {
                "service": "WFS", "version": "2.0.0", "request": "DescribeFeatureType",
                "typeNames": typename, "outputFormat": "application/json"})
            field = "geom"
            for ft in payload.get("featureTypes", []):
                for prop in ft.get("properties", []):
                    if str(prop.get("type", "")).startswith("gml:"):
                        field = prop["name"]
                        break
            self._geom_cache[typename] = field
        return self._geom_cache[typename]

    def get_features(self, typename: str, cql: str, max_features: Optional[int] = None) -> List[Feature]:
        out: List[Feature] = []
        start = 0
        while True:
            count = self.page_size if max_features is None else min(self.page_size, max_features - len(out))
            if count <= 0:
                break
            payload = self.client.get_json(self.url, {
                "service": "WFS", "version": "2.0.0", "request": "GetFeature", "typeNames": typename,
                "outputFormat": "application/json", "srsName": "EPSG:31370", "CQL_FILTER": cql,
                "count": count, "startIndex": start})
            feats = payload.get("features", [])
            out.extend(feats)
            matched = payload.get("numberMatched")
            if len(feats) < count or (isinstance(matched, int) and len(out) >= matched):
                break
            start += len(feats)
        return out

    def within_distance(self, typename: str, zone_wkt: str, distance_m: float,
                        max_features: Optional[int] = None) -> List[Feature]:
        g = self.geometry_field(typename)
        return self.get_features(typename, f"DWITHIN({g},{zone_wkt},{distance_m:g},meters)", max_features)

    def intersecting(self, typename: str, zone_wkt: str, max_features: Optional[int] = None) -> List[Feature]:
        g = self.geometry_field(typename)
        return self.get_features(typename, f"INTERSECTS({g},{zone_wkt})", max_features)
