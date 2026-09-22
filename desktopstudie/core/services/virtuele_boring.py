"""DOV virtual borehole API. Two endpoints, one layer catalogue:

- 'doorprik': one point, data[] = {name, top, base, thickness} in mTAW.
- 'profielbevraging': a whole line, data[] = one record per distance step holding only
  THICKNESSES per layer code (0.0 = absent) plus 'dist'; no elevations at all, so a caller
  stacks the record downwards from a surface it knows.

Both answers carry layers[] = metadata keyed by code (name, beschrijving, dovlayercolor,
texturen). A profile record has two entries that are not model layers: 'dist' (the chainage) and
'INV' (bottom padding, see PROFILE_PADDING_CODE)."""
from __future__ import annotations

from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from .. import geometry
from ..catalogue import VB_DOORPRIK_URL, VB_PROFILE_URL
from ..logging_util import Log
from ..model import ProfileColumn, SectionProfile, VbLayer, VirtualBorehole

FALLBACK_COLOR = "#cccccc"
# The chainage entry of a profile record: never a thickness.
PROFILE_DISTANCE_KEY = "dist"
# 'INV' is the bottom padding of a column in a model with knownLowBoundary=true (hcovv1): the
# column stops at the model's real base and INV fills the rest down to the answer's common floor.
# It therefore COUNTS towards the thickness sum that gives the surface, but it is never drawn.
# Live check 2026-09-15 (hcovv1, line 104126/192506 -> 104526/192506): INV runs 0.00 - 1.05 m and
# only minValue + the sum INCLUDING INV reproduces the doorprik tops 8.38 / 11.55 / 14.59 / 17.79 /
# 21.36 mTAW; leaving it out puts the surface up to a metre too low.
PROFILE_PADDING_CODE = "INV"
# How far the stacked surface may sit from the answer's own maxValue before the datum is refused.
PROFILE_DATUM_TOLERANCE_M = 0.05


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


def fetch_virtual_borehole(client, x: float, y: float, model: str,
                           log: Optional[Log] = None) -> VirtualBorehole:
    """The doorprik at one point. A point outside the model answers HTTP 200 with an empty data[],
    so an empty borehole is a normal answer, not an error - it is WARNED about rather than handed
    back silently, because an empty column in the report otherwise reads as ground without
    geology."""
    params = {"x": f"{x:.2f}", "y": f"{y:.2f}", "crs": "EPSG:31370"}
    payload = client.get_json(VB_DOORPRIK_URL.format(model=model), params)
    borehole = parse_doorprik(payload, x, y, model)
    if not borehole.layers and log:
        log.warning(f"virtuele boring {model} op {x:.0f}/{y:.0f}: geen lagen")
    return borehole


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


def _is_thickness(key: str, value: Any) -> bool:
    """True when this record entry is a positive layer thickness. The chainage never is one; the
    padding code IS one (it takes up vertical space) even though it is not a drawable layer, so
    both the surface sum and the drawn stack start from this single predicate."""
    return (key != PROFILE_DISTANCE_KEY and isinstance(value, (int, float))
            and not isinstance(value, bool) and value > 0)


def _usable_records(payload: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[float]]:
    """Splits the records into those with at least one DRAWABLE layer and the chainages of the ones
    without. A column where every layer is 0.0 lies outside the model: it has neither a surface nor
    a layer, so it must leave a gap rather than a zero-height column at the floor. Bottom padding
    does not rescue such a column - a record whose only positive entry is the padding has no
    geology either, and keeping it would hang an empty column at floor + padding and drag the
    interpolated surface down to it."""
    usable: List[Dict[str, Any]] = []
    empty: List[float] = []
    for record in payload.get("data") or []:
        if any(_is_thickness(key, value) and key != PROFILE_PADDING_CODE
               for key, value in record.items()):
            usable.append(record)
        else:
            empty.append(float(record.get(PROFILE_DISTANCE_KEY, 0.0)))
    return usable, empty


def _column_surface(floor: float, record: Dict[str, Any]) -> float:
    return floor + sum(value for key, value in record.items() if _is_thickness(key, value))


def profile_surface_at(payload: Dict[str, Any],
                       log: Optional[Log] = None) -> Optional[Callable[[float], float]]:
    """A surface function straight from the profile answer, or None when it carries no usable datum.

    DOV pads every column of a profile answer down to one common floor, reported as `minValue`, so
    that floor plus the column's own thickness sum (INCLUDING the `INV` padding) is exactly the
    modelled surface there. Verified live on 2026-09-15 against the doorprik at 17 points over a
    78 km line (Ronse -> Antwerpen, model base -165 to -711 mTAW) and on hcovv1, which pads: the
    two agree to the centimetre everywhere. Preferring this over a surface interpolated between
    far-apart anchors matters because the G3Dv3 grid is 100 m - with an interpolated surface the
    layer boundaries inside one grid cell tilt with the interpolation and jump back at the cell
    edge, which looks like sawtooth geology that is not in the model.

    The answer states its own highest surface as `maxValue`. When the stacked surfaces disagree
    with it, the datum is not what this function assumes, so it is refused (WARNING) and the caller
    falls back to its own surface rather than drawing a section that is metres off. Columns outside
    the model carry no surface and stay out of the interpolation."""
    floor = payload.get("minValue")
    usable, _ = _usable_records(payload)
    if floor is None or not usable:
        return None
    dists = [float(record[PROFILE_DISTANCE_KEY]) for record in usable]
    surfaces = [_column_surface(float(floor), record) for record in usable]
    highest = payload.get("maxValue")
    if highest is not None and abs(max(surfaces) - float(highest)) > PROFILE_DATUM_TOLERANCE_M:
        if log:
            log.warning(f"profielmaaiveld {max(surfaces):.2f} mTAW wijkt af van maxValue "
                        f"{float(highest):.2f} mTAW; datum niet gebruikt")
        return None

    def surface_at(along: float) -> float:
        return geometry.interpolate(along, dists, surfaces)

    return surface_at


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
                  surface_at: Callable[[float], float], resolution_m: Optional[float] = None,
                  log: Optional[Log] = None) -> SectionProfile:
    """Turn the thickness records into columns of VbLayer stacked down from `surface_at(along)`.
    A column without a single layer lies outside the model and is left out (reported via `log`), so
    the figure shows a gap there. `resolution_m` defaults to the sampling step the service reports;
    pass the requested step when the caller wants that recorded instead."""
    meta = {layer.get("code"): layer for layer in payload.get("layers", []) if isinstance(layer, dict)}
    usable, empty = _usable_records(payload)
    if empty and log:
        log.warning(f"profiel {model}: {len(empty)} kolom(men) zonder lagen overgeslagen (buiten het "
                    f"model) op {', '.join(format(along, '.0f') for along in empty)} m")
    columns: List[ProfileColumn] = []
    for record in usable:
        along = float(record[PROFILE_DISTANCE_KEY])
        surface = float(surface_at(along))
        present = [code for code, value in record.items()
                   if _is_thickness(code, value) and code != PROFILE_PADDING_CODE]
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

