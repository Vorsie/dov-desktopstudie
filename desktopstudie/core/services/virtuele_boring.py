"""DOV virtual borehole API. Two endpoints, one layer catalogue:

- 'doorprik': one point, data[] = {name, top, base, thickness} in mTAW.
- 'profielbevraging': a whole line, data[] = one record per distance step holding only
  THICKNESSES per layer code (0.0 = absent) plus 'dist'; no elevations at all, so a caller
  stacks the record downwards from a surface it knows.

Both answers carry layers[] = metadata keyed by code (name, beschrijving, dovlayercolor,
texturen); the profile answer adds the pseudo-layers 'dist' and 'INV'."""
from __future__ import annotations

from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

from ..catalogue import VB_DOORPRIK_URL, VB_PROFILE_URL
from ..logging_util import Log
from ..model import ProfileColumn, SectionProfile, VbLayer, VirtualBorehole

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
# Columns of a profile record that are not model layers.
PROFILE_PSEUDO_LAYERS = ("dist", "INV")


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


def fetch_profile(client, model: str, p, q, resolution_m: float, log: Optional[Log] = None) -> Dict[str, Any]:
    """Raw profile answer for the line p -> q, sampled every `resolution_m` metres. Returned as the
    payload rather than a parsed profile because stacking it needs a surface the caller owns."""
    params = {"xValues": f"{p[0]:.2f},{q[0]:.2f}", "yValues": f"{p[1]:.2f},{q[1]:.2f}",
              "resolution": int(resolution_m)}
    payload = client.get_json(VB_PROFILE_URL.format(model=model), params)
    if not payload.get("data"):
        if log:
            log.warning(f"profiel {model} langs {p[0]:.0f}/{p[1]:.0f} - {q[0]:.0f}/{q[1]:.0f} is leeg")
    return payload


def _code_rank(code: str) -> int:
    """The numeric suffix of a DOV layer code ('g3dv3_F_31' -> 31). The models number their units
    from top to bottom, so the suffix orders them stratigraphically."""
    tail = code.rsplit("_", 1)[-1]
    return int(tail) if tail.isdigit() else -1


def _stack_order(order: Sequence[str], codes: Iterable[str]) -> List[str]:
    """Top-to-bottom order for one profile record. `order` (the anchor doorprik's own sequence)
    wins for the codes it covers; a code the anchor did not have is slotted in by its numeric
    suffix, so a shallow unit missing from the anchor lands near the surface instead of below the
    deepest one."""
    ranks = [_code_rank(c) for c in order]
    index_of = {code: i for i, code in enumerate(order)}

    def slot(code: str):
        if code in index_of:
            return (index_of[code], 0, 0)
        rank = _code_rank(code)
        return (sum(1 for r in ranks if r < rank), -1, rank)  # -1: just above the first deeper unit

    return sorted(codes, key=slot)


def parse_profile(payload: Dict[str, Any], model: str, order: Sequence[str],
                  surface_at: Callable[[float], float],
                  resolution_m: Optional[float] = None) -> SectionProfile:
    """Turn the thickness records into columns of VbLayer stacked down from `surface_at(along)`.
    `resolution_m` defaults to the sampling step the service reports; pass the requested step when
    the caller wants that recorded instead."""
    meta = {layer.get("code"): layer for layer in payload.get("layers", []) if isinstance(layer, dict)}
    columns: List[ProfileColumn] = []
    for record in payload.get("data", []):
        along = float(record["dist"])
        surface = float(surface_at(along))
        present = [code for code, value in record.items()
                   if code not in PROFILE_PSEUDO_LAYERS and isinstance(value, (int, float)) and value > 0]
        top = surface
        layers: List[VbLayer] = []
        for code in _stack_order(order, present):
            info = meta.get(code, {})
            thickness = float(record[code])
            layers.append(VbLayer(
                code=code,
                name=info.get("name") or code,
                top_mtaw=top,
                base_mtaw=top - thickness,
                thickness_m=thickness,
                color=info.get("dovlayercolor") or FALLBACK_COLOR,
                texture=info.get("texturen") or "",
            ))
            top -= thickness
        columns.append(ProfileColumn(along_m=along, surface_mtaw=surface, layers=layers))
    if resolution_m is None:
        resolution_m = float(payload.get("resolution") or 0.0)
    return SectionProfile(model=model, resolution_m=float(resolution_m), columns=columns)


def layers_named(borehole: VirtualBorehole, name: str) -> List[VbLayer]:
    """Layers whose name starts with `name`, case-insensitively (DOV varies capitalisation and
    appends suffixes such as sub-member names to an otherwise-matching layer name).

    Caveat: this is a prefix match, so a short name can collide with an unrelated, more specific
    one — "Formatie van Gent" also matches "Formatie van Gentbrugge". Callers should pass short,
    unambiguous names ("antropogeen", "quartair") that have no such longer sibling in the model.
    """
    needle = name.strip().lower()
    return [layer for layer in borehole.layers if layer.name.lower().startswith(needle)]


def base_of(borehole: VirtualBorehole, name: str) -> Optional[float]:
    """Base elevation (mTAW) of the deepest layer whose name starts with `name` (see `layers_named`,
    including its prefix-collision caveat)."""
    matches = layers_named(borehole, name)
    return min(layer.base_mtaw for layer in matches) if matches else None
