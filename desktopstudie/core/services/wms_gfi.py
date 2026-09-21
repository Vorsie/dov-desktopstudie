"""WMS 1.3.0 GetFeatureInfo at a point, GeoJSON output (ArcGIS-served layers accept
application/geo+json). Returns the properties of each feature plus its layerName."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..logging_util import Log

GRID = 101  # beeldpunten over de doos; oneven, zodat het gevraagde punt het middelste is
MIN_GRID = 3


def _grid(half_size_m: float, m_per_pixel: float) -> int:
    """Hoeveel beeldpunten over de doos, zodat een beeldpunt minstens `m_per_pixel` breed is.

    Altijd oneven: het gevraagde punt moet het MIDDELSTE beeldpunt zijn, en een even rooster heeft
    geen midden.
    """
    if m_per_pixel <= 0:
        return GRID
    size = min(GRID, int(2 * half_size_m / m_per_pixel))
    if size % 2 == 0:
        size += 1
    return max(MIN_GRID, size)


def feature_info_at_point(client, wms_url: str, layer: str, x: float, y: float,
                          half_size_m: float = 50.0, info_format: str = "application/geo+json",
                          log: Optional[Log] = None,
                          m_per_pixel: float = 0.0) -> List[Dict[str, Any]]:
    """Zero features is the ordinary answer for a point outside the mapped area - most of the
    catalogue's GFI layers cover only part of Flanders - so the count goes to DEBUG, not WARNING;
    it is still logged, because "the map said nothing here" and "the map was never asked" look
    identical in the report otherwise.

    `m_per_pixel` is how COARSE this coverage wants to be asked. A raster whose cells are 100 m
    answers a question posed at one metre per pixel with nothing at all - not an error, just an
    empty FeatureCollection, which reads in the report as "the map says nothing here" over a map
    that plainly carries a class. Left at 0 the grid stays fine, because asking a fine coverage
    coarsely averages its neighbours in: the same GLG point moves from 3,54 to 3,52 m at nine
    metres per pixel. So the coarse ones say so themselves (`catalogue.MapEntry.gfi_m_per_pixel`).
    """
    size = _grid(half_size_m, m_per_pixel)
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
