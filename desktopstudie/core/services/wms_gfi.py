"""WMS 1.3.0 GetFeatureInfo at a point, GeoJSON output (ArcGIS-served layers accept
application/geo+json). Returns the properties of each feature plus its layerName."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..logging_util import Log


def feature_info_at_point(client, wms_url: str, layer: str, x: float, y: float,
                          half_size_m: float = 50.0, info_format: str = "application/geo+json",
                          log: Optional[Log] = None) -> List[Dict[str, Any]]:
    """Zero features is the ordinary answer for a point outside the mapped area - most of the
    catalogue's GFI layers cover only part of Flanders - so the count goes to DEBUG, not WARNING;
    it is still logged, because "the map said nothing here" and "the map was never asked" look
    identical in the report otherwise."""
    size = 101
    bbox = (f"{x - half_size_m:.2f},{y - half_size_m:.2f},"
            f"{x + half_size_m:.2f},{y + half_size_m:.2f}")
    payload = client.get_json(wms_url, {
        "service": "WMS", "version": "1.3.0", "request": "GetFeatureInfo",
        "layers": layer, "query_layers": layer, "styles": "", "crs": "EPSG:31370",
        "bbox": bbox, "width": size, "height": size, "i": size // 2, "j": size // 2,
        "format": "image/png", "info_format": info_format, "feature_count": 10})
    rows: List[Dict[str, Any]] = []
    for feat in payload.get("features", []):
        props = dict(feat.get("properties", {}))
        props["layerName"] = feat.get("layerName", "")
        rows.append(props)
    if log:
        log.debug(f"GetFeatureInfo {layer} op {x:.0f}/{y:.0f}: {len(rows)} object(en)")
    return rows
