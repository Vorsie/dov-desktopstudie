"""DOV virtual borehole ('doorprik') API. Response: data[] = {name, top, base, thickness} in mTAW,
layers[] = metadata keyed by code (name, beschrijving, dovlayercolor, texturen)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..catalogue import VB_DOORPRIK_URL
from ..model import VbLayer, VirtualBorehole

MODEL_TITLES = {
    "g3dv3_F": "G3Dv3 - formaties",
    "g3dv3_L": "G3Dv3 - leden",
    "g3dv3_P": "G3Dv3 - periodes",
    "g3dv3_T": "G3Dv3 - tijdvakken",
    "hcovv1": "HCOV v1",
    "hcovv2_H": "HCOV v2 - hoofdeenheden",
    "hcovv2_S": "HCOV v2 - subeenheden",
    "hcovv2_B": "HCOV v2 - basiseenheden",
}
FALLBACK_COLOR = "#cccccc"


def parse_doorprik(payload: Dict[str, Any], x: float, y: float, model: str) -> VirtualBorehole:
    meta = {layer.get("code"): layer for layer in payload.get("layers", []) if isinstance(layer, dict)}
    layers = []
    for row in payload.get("data", []):
        info = meta.get(row.get("name"), {})
        top, base = float(row["top"]), float(row["base"])
        thickness = row.get("thickness")
        if thickness is None:
            thickness = top - base
        layers.append(VbLayer(
            code=str(row.get("name")),
            name=info.get("name") or str(row.get("name")),
            top_mtaw=top,
            base_mtaw=base,
            thickness_m=float(thickness),
            color=info.get("dovlayercolor") or FALLBACK_COLOR,
            texture=info.get("texturen") or "",
        ))
    return VirtualBorehole(x=x, y=y, model=model, layers=layers)


def fetch_virtual_borehole(client, x: float, y: float, model: str) -> VirtualBorehole:
    params = {"x": f"{x:.2f}", "y": f"{y:.2f}", "crs": "EPSG:31370"}
    payload = client.get_json(VB_DOORPRIK_URL.format(model=model), params)
    return parse_doorprik(payload, x, y, model)


def layers_named(borehole: VirtualBorehole, name: str) -> List[VbLayer]:
    """Layers whose name starts with `name`, case-insensitively (DOV varies capitalisation and
    appends suffixes such as sub-member names to an otherwise-matching layer name)."""
    needle = name.strip().lower()
    return [layer for layer in borehole.layers if layer.name.lower().startswith(needle)]


def base_of(borehole: VirtualBorehole, name: str) -> Optional[float]:
    """Base elevation (mTAW) of the deepest layer whose name starts with `name` (see `layers_named`)."""
    matches = layers_named(borehole, name)
    return min(layer.base_mtaw for layer in matches) if matches else None
