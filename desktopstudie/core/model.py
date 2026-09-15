# desktopstudie/core/model.py
"""Domain dataclasses. Depths: '_m' = metres below surface (positive down); '_mtaw' = elevation."""
from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import geometry

Point = Tuple[float, float]


@dataclass
class StudyZone:
    ring: List[Point]
    name: str
    radius_m: float = 500.0
    section_line: Optional[Tuple[Point, Point]] = None
    address: Optional[str] = None

    @property
    def centroid(self) -> Point:
        return geometry.centroid(self.ring)

    @property
    def bbox(self) -> Tuple[float, float, float, float]:
        return geometry.bbox(self.ring)

    @property
    def wkt(self) -> str:
        return geometry.polygon_wkt(self.ring)

    @property
    def area_m2(self) -> float:
        return geometry.area(self.ring)


@dataclass
class Provenance:
    source: str
    url: str
    retrieved_at: str
    ok: bool = True
    message: str = ""


@dataclass
class CptProfile:
    depth_m: List[float]
    qc_mpa: List[Optional[float]]
    fs_kpa: List[Optional[float]]
    u_kpa: List[Optional[float]]


@dataclass
class Cpt:
    permkey: str
    number: str
    x: float
    y: float
    z_mtaw: Optional[float]
    depth_m: Optional[float]
    date: Optional[str]
    method: Optional[str]
    cone: Optional[str]
    contractor: Optional[str]
    project: Optional[str]
    url: str
    distance_m: float
    profile: Optional[CptProfile] = None


@dataclass
class LithologyLayer:
    top_m: float
    base_m: float
    description: str
    kind: str = "beschrijving"  # or "gecodeerd"


@dataclass
class Borehole:
    permkey: str
    number: str
    x: float
    y: float
    z_mtaw: Optional[float]
    depth_m: Optional[float]
    date: Optional[str]
    method: Optional[str]
    purpose: Optional[str]
    contractor: Optional[str]
    url: str
    distance_m: float
    interpretation_url: Optional[str] = None
    lithology: List[LithologyLayer] = field(default_factory=list)


@dataclass
class GwLevel:
    date: str
    level_mtaw: float
    method: Optional[str] = None
    reliability: Optional[str] = None


@dataclass
class GwFilter:
    gw_id: str
    filter_no: str
    x: float
    y: float
    z_mtaw: Optional[float]
    aquifer: Optional[str]
    filter_base_m: Optional[float]
    filter_length_m: Optional[float]
    network: Optional[str]
    url: str
    report_url: Optional[str]
    distance_m: float
    levels_from: Optional[str] = None
    levels_to: Optional[str] = None
    latest: Optional[GwLevel] = None

    @property
    def latest_depth_m(self) -> Optional[float]:
        if self.latest is None or self.z_mtaw is None:
            return None
        return self.z_mtaw - self.latest.level_mtaw


@dataclass
class VbLayer:
    code: str
    name: str
    top_mtaw: float
    base_mtaw: float
    thickness_m: float
    color: str
    texture: str


@dataclass
class VirtualBorehole:
    x: float
    y: float
    model: str
    layers: List[VbLayer]

    @property
    def surface_mtaw(self) -> Optional[float]:
        return self.layers[0].top_mtaw if self.layers else None

    def depth_of(self, layer: VbLayer) -> Tuple[float, float]:
        surface = self.surface_mtaw or 0.0
        return surface - layer.top_mtaw, surface - layer.base_mtaw


@dataclass
class ProjectedPoint:
    kind: str  # "cpt" | "boring" | "peilput"
    label: str
    along_m: float
    offset_m: float
    z_mtaw: Optional[float]
    depth_m: Optional[float]


@dataclass
class Section:
    line: Tuple[Point, Point]
    boreholes: List[VirtualBorehole]
    projected: List[ProjectedPoint]
    zone_from_m: float
    zone_to_m: float


@dataclass
class MapFact:
    map_id: str
    title: str
    rows: List[Dict[str, Any]]


@dataclass
class Signalering:
    code: str
    fact: str
    source: str
    advice: str
    severity: str = "aandacht"  # "info" | "aandacht"


@dataclass
class StudyResult:
    zone: StudyZone
    created_at: str
    municipality: Optional[str] = None
    cpts: List[Cpt] = field(default_factory=list)
    boreholes: List[Borehole] = field(default_factory=list)
    gw_filters: List[GwFilter] = field(default_factory=list)
    virtual_boreholes: Dict[str, VirtualBorehole] = field(default_factory=dict)
    section: Optional[Section] = None
    map_facts: List[MapFact] = field(default_factory=list)
    signaleringen: List[Signalering] = field(default_factory=list)
    provenance: List[Provenance] = field(default_factory=list)
    figures: Dict[str, str] = field(default_factory=dict)
    relief: Optional[Tuple[float, float, float]] = None  # (min, max, mean) mTAW, filled by the shell

    def summary(self) -> Dict[str, Any]:
        return {
            "n_cpts": len(self.cpts),
            "n_boreholes": len(self.boreholes),
            "n_gw_filters": len(self.gw_filters),
            "n_signaleringen": len(self.signaleringen),
            "n_sources_failed": sum(1 for p in self.provenance if not p.ok),
        }

    def to_dict(self) -> Dict[str, Any]:
        data = dataclasses.asdict(self)
        data["summary"] = self.summary()
        return data

    def write_json(self, path: Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=1), encoding="utf-8")
