"""DOV WFS 2.0.0 access. Rules learned from the live service: never send BBOX together with
CQL_FILTER (fold spatial predicates into CQL); no hard per-response limit was observed on
2026-09-15; page with startIndex/count (page_size 500 as a safe default), de-duplicate across
pages, and report truncation; the geometry attribute name differs per layer
(geom/shape/geometry/the_geom), so look it up with DescribeFeatureType once per layer."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple

from ..catalogue import DOV_WFS_URL
from ..logging_util import Log

Feature = Dict[str, Any]


def _first_gml_property(payload: Dict[str, Any]) -> Optional[str]:
    for ft in payload.get("featureTypes", []):
        for prop in ft.get("properties", []):
            if str(prop.get("type", "")).startswith("gml:"):
                return prop["name"]
    return None


def feature_xy(feature: Feature) -> Tuple[float, float]:
    geometry = feature.get("geometry")
    if geometry is None:
        raise ValueError(f"feature {feature.get('id')} heeft geen geometrie")
    coords = geometry["coordinates"]
    return float(coords[0]), float(coords[1])


class DovWfs:
    def __init__(self, client, page_size: int = 500, log: Optional[Log] = None):
        self.client = client
        self.url = DOV_WFS_URL
        self.page_size = page_size
        self.log = log
        self._geom_cache: Dict[str, str] = {}
        self.truncations: List[Tuple[str, int, int]] = []

    def geometry_field(self, typename: str) -> str:
        if typename not in self._geom_cache:
            payload = self.client.get_json(self.url, {
                "service": "WFS", "version": "2.0.0", "request": "DescribeFeatureType",
                "typeNames": typename, "outputFormat": "application/json"})
            field = _first_gml_property(payload)
            if field is None:
                raise ValueError(f"geen gml-geometrieveld in DescribeFeatureType voor {typename}")
            self._geom_cache[typename] = field
        return self._geom_cache[typename]

    def get_features(self, typename: str, cql: str, max_features: Optional[int] = None) -> List[Feature]:
        # cql is always assembled internally from catalogue typenames and our own zone WKT, never
        # from unsanitised user input, so there is no CQL-injection surface to defend against here.
        out: List[Feature] = []
        seen_ids: Set[Any] = set()
        fetched = 0
        start = 0
        matched: Optional[int] = None
        while True:
            count = self.page_size if max_features is None else min(self.page_size, max_features - fetched)
            if count <= 0:
                break
            payload = self.client.get_json(self.url, {
                "service": "WFS", "version": "2.0.0", "request": "GetFeature", "typeNames": typename,
                "outputFormat": "application/json", "srsName": "EPSG:31370", "CQL_FILTER": cql,
                "count": count, "startIndex": start})
            feats = payload.get("features", [])
            fetched += len(feats)
            for feat in feats:
                fid = feat.get("id")
                if fid is not None:
                    if fid in seen_ids:
                        continue
                    seen_ids.add(fid)
                out.append(feat)
            if matched is None:
                # numberMatched is taken from the first page that carries it; a later page
                # omitting the field must never reset an already-learned value back to None.
                page_matched = payload.get("numberMatched")
                if isinstance(page_matched, int):
                    matched = page_matched
            if len(feats) < count or (isinstance(matched, int) and fetched >= matched):
                break
            start += len(feats)
        # Truncation (the server withheld data) and de-duplication (repeated feature ids across
        # pages) have independent causes, so report them independently -- a hybrid case must
        # still record the truncation even though de-duplication also happened.
        dropped = fetched - len(out)
        if dropped > 0 and self.log:
            self.log.debug(f"{typename}: {dropped} dubbele features over pagina's verwijderd")
        if isinstance(matched, int) and fetched < matched:
            self.truncations.append((typename, len(out), matched))
            if self.log:
                self.log.warning(f"{typename}: {len(out)} van {matched} features opgehaald "
                                  f"(max_features={max_features})")
        elif isinstance(matched, int) and fetched >= matched and len(out) < matched:
            if self.log:
                self.log.warning(f"{typename}: server leverde {len(out)} unieke van {matched} "
                                  f"features (dubbele over pagina's)")
        return out

    def within_distance(self, typename: str, zone_wkt: str, distance_m: float,
                        max_features: Optional[int] = None) -> List[Feature]:
        g = self.geometry_field(typename)
        return self.get_features(typename, f"DWITHIN({g},{zone_wkt},{distance_m:g},meters)", max_features)

    def intersecting(self, typename: str, zone_wkt: str, max_features: Optional[int] = None) -> List[Feature]:
        g = self.geometry_field(typename)
        return self.get_features(typename, f"INTERSECTS({g},{zone_wkt})", max_features)
