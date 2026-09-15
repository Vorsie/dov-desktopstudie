"""Orchestrates one desktop study: fetch -> parse -> section -> facts -> checks -> figures -> JSON.
Every stage is guarded: a failure becomes a Provenance(ok=False) and the run continues."""
from __future__ import annotations

import datetime as dt
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from . import catalogue, checks, geometry
from .figures import borehole_column, cpt_figure, section_figure, vb_column
from .logging_util import Log
from .model import Borehole, Cpt, GwFilter, MapFact, Provenance, Signalering, StudyResult, StudyZone
from .section import build_section, section_line
from .services import dov_xml, wms_gfi
from .services.dov_wfs import DovWfs, feature_xy
from .services.virtuele_boring import fetch_virtual_borehole

Progress = Callable[[float, str], None]


@dataclass
class Settings:
    radius_m: float = 500.0
    n_cpt_figures: int = 5
    n_borehole_figures: int = 5
    n_gw_levels: int = 5
    section_extension_m: float = 100.0
    n_section_points: int = 11
    corridor_m: float = 50.0
    models_centroid: Tuple[str, ...] = ("g3dv3_F", "g3dv3_L", "g3dv3_P", "hcovv2_S")  # F: antropogeen only exists there
    model_section: str = "g3dv3_F"
    with_profile: bool = True
    max_features: int = 2000
    max_workers: int = 4
    map_ids: Optional[List[str]] = field(default=None)  # None = all enabled catalogue entries


def _now() -> str:
    return dt.datetime.now().replace(microsecond=0).isoformat()


def _prop(props, key, cast=None):
    value = props.get(key)
    if value in (None, ""):
        return None
    return cast(value) if cast else value


class _Runner:
    def __init__(self, zone: StudyZone, settings: Settings, client, out_dir: Path,
                 progress: Optional[Progress], log: Log):
        self.zone = zone
        self.s = settings
        self.client = client
        self.out = Path(out_dir)
        self.progress = progress or (lambda f, m: None)
        self.log = log
        self.wfs = DovWfs(client, log=log.child("dov_wfs"))
        self.result = StudyResult(zone=zone, created_at=_now())
        self.zone.radius_m = settings.radius_m

    def guarded(self, source: str, url: str, fn: Callable[[], None]) -> None:
        try:
            fn()
            self.result.provenance.append(Provenance(source, url, _now(), True))
        except Exception as exc:  # noqa: BLE001 - isolate every source
            self.log.warning(f"{source} niet beschikbaar: {exc}")
            self.result.provenance.append(Provenance(source, url, _now(), False, f"{type(exc).__name__}: {exc}"))

    def dist(self, x: float, y: float) -> float:
        return geometry.distance_to_ring((x, y), self.zone.ring)

    def _relative(self, path: Path) -> str:
        """Figure paths in the JSON are relative to the output directory and use forward slashes,
        so a result written on Windows still resolves on another machine."""
        return Path(path).relative_to(self.out).as_posix()

    # --- stages -------------------------------------------------------------------------
    def cpts(self) -> None:
        feats = self.wfs.within_distance("dov-pub:Sonderingen", self.zone.wkt, self.s.radius_m, self.s.max_features)
        out: List[Cpt] = []
        for f in feats:
            p = f["properties"]
            x, y = feature_xy(f)
            url = p.get("fiche") or ""
            out.append(Cpt(permkey=url.rsplit("/", 1)[-1], number=p.get("sondeernummer") or "?", x=x, y=y,
                           z_mtaw=_prop(p, "Z_mTAW", float), depth_m=_prop(p, "diepte_tot_m", float),
                           date=_prop(p, "datum_aanvang"), method=_prop(p, "sondeermethode"),
                           cone=_prop(p, "conus"), contractor=_prop(p, "uitvoerder"),
                           project=_prop(p, "opdrachten"), url=url, distance_m=self.dist(x, y)))
        out.sort(key=lambda c: c.distance_m)
        self.result.cpts = out
        self.result.municipality = self.result.municipality or next(
            (f["properties"].get("gemeente") for f in feats if f["properties"].get("gemeente")), None)
        nearest = [c for c in out if c.url][: self.s.n_cpt_figures]

        def load(c: Cpt) -> None:
            c.profile = dov_xml.parse_cpt_profile(self.client.get(c.url + ".xml"), log=self.log.child("dov_xml"))

        with ThreadPoolExecutor(max_workers=self.s.max_workers) as pool:
            list(pool.map(load, nearest))
        self.log.info(f"{len(out)} sonderingen binnen {self.s.radius_m:.0f} m, {len(nearest)} met meetreeks")

    def boreholes(self) -> None:
        feats = self.wfs.within_distance("dov-pub:Boringen", self.zone.wkt, self.s.radius_m, self.s.max_features)
        interp = {}
        for typename in ("interpretaties:lithologische_beschrijvingen", "interpretaties:gecodeerde_lithologie"):
            for f in self.wfs.within_distance(typename, self.zone.wkt, self.s.radius_m, self.s.max_features):
                p = f["properties"]
                interp.setdefault(p.get("Proeffiche"), p.get("Interpretatiefiche"))
        out: List[Borehole] = []
        for f in feats:
            p = f["properties"]
            x, y = feature_xy(f)
            url = p.get("fiche") or ""
            out.append(Borehole(permkey=url.rsplit("/", 1)[-1], number=p.get("boornummer") or "?", x=x, y=y,
                                z_mtaw=_prop(p, "Z_mTAW", float), depth_m=_prop(p, "diepte_tot_m", float),
                                date=_prop(p, "datum_aanvang"), method=_prop(p, "methode"),
                                purpose=_prop(p, "doel"), contractor=_prop(p, "uitvoerder"), url=url,
                                distance_m=self.dist(x, y), interpretation_url=interp.get(url)))
        out.sort(key=lambda b: b.distance_m)
        self.result.boreholes = out
        nearest = [b for b in out if b.interpretation_url][: self.s.n_borehole_figures]

        def load(b: Borehole) -> None:
            b.lithology = dov_xml.parse_lithology(self.client.get(b.interpretation_url + ".xml"),
                                                  log=self.log.child("dov_xml"))

        with ThreadPoolExecutor(max_workers=self.s.max_workers) as pool:
            list(pool.map(load, nearest))
        self.log.info(f"{len(out)} boringen, {sum(1 for b in out if b.interpretation_url)} met lithologie, "
                      f"{len(nearest)} opgehaald")

    def groundwater(self) -> None:
        feats = self.wfs.within_distance("gw_meetnetten:grondwaterlocaties_met_metingen", self.zone.wkt,
                                         self.s.radius_m, self.s.max_features)
        out: List[GwFilter] = []
        for f in feats:
            p = f["properties"]
            x, y = feature_xy(f)
            out.append(GwFilter(gw_id=p.get("GW_ID") or "?", filter_no=str(p.get("filternummer") or "1"), x=x, y=y,
                                z_mtaw=_prop(p, "Z_mTAW", float), aquifer=_prop(p, "Aquifer_HCOVv2"),
                                filter_base_m=_prop(p, "onderkant_filter_m", float),
                                filter_length_m=_prop(p, "lengte_filter_m", float),
                                network=_prop(p, "meetnet"), url=p.get("filterfiche") or "",
                                report_url=_prop(p, "stijghoogterapport"), distance_m=self.dist(x, y),
                                levels_from=_prop(p, "peilmetingen_van"), levels_to=_prop(p, "peilmetingen_tot")))
        out.sort(key=lambda g: g.distance_m)
        self.result.gw_filters = out
        nearest = [g for g in out if g.levels_to and g.url][: self.s.n_gw_levels]

        def load(g: GwFilter) -> None:
            levels = dov_xml.parse_groundwater_levels(self.client.get(g.url + ".xml"), log=self.log.child("dov_xml"))
            g.latest = levels[-1] if levels else None

        with ThreadPoolExecutor(max_workers=self.s.max_workers) as pool:
            list(pool.map(load, nearest))
        self.log.info(f"{len(out)} peilputten, {sum(1 for g in out if g.latest)} met laatste peil")

    def virtual_boreholes(self) -> None:
        cx, cy = self.zone.representative_point  # inside the zone, also for L-shaped parcels
        for model in self.s.models_centroid:
            self.guarded(f"Virtuele boring {model}", catalogue.VB_DOORPRIK_URL.format(model=model),
                         lambda m=model: self.result.virtual_boreholes.__setitem__(
                             m, fetch_virtual_borehole(self.client, cx, cy, m)))

    def section(self) -> None:
        if self.zone.section_line is None:
            self.zone.section_line = section_line(self.zone, self.s.section_extension_m)
        self.result.section = build_section(
            self.client, self.zone.section_line, self.zone, self.result.cpts, self.result.boreholes,
            self.result.gw_filters, self.s.n_section_points, self.s.corridor_m, self.s.model_section,
            log=self.log.child("section"), max_workers=self.s.max_workers, with_profile=self.s.with_profile)

    def map_facts(self) -> None:
        wanted = catalogue.entries("geologie")
        if self.s.map_ids is not None:
            wanted = [e for e in wanted if e.id in self.s.map_ids]
        for entry in wanted:
            if entry.fact_mode is None:
                continue

            def fetch(e=entry) -> None:
                if e.fact_mode == "wfs":
                    feats = self.wfs.intersecting(e.wfs_typename, self.zone.wkt, self.s.max_features)
                    rows = [{k: f["properties"].get(k) for k in e.fact_fields} for f in feats]
                else:
                    rows = []
                    seen = set()
                    for x, y in [self.zone.representative_point] + list(self.zone.ring[:8]):
                        for row in wms_gfi.feature_info_at_point(self.client, e.wms_url, e.wms_layer, x, y):
                            key = tuple(str(row.get(k)) for k in e.fact_fields)
                            if key not in seen:
                                seen.add(key)
                                rows.append({k: row.get(k) for k in e.fact_fields})
                self.result.map_facts.append(MapFact(e.id, e.title, rows))
                self.log.debug(f"{e.id}: {len(rows)} eenheden in de zone")

            url = entry.wms_url if entry.fact_mode == "gfi" else catalogue.DOV_WFS_URL
            self.guarded(f"{entry.title} (feiten)", url, fetch)

    def _truncation_signals(self) -> List[Signalering]:
        """WFS results cut off by max_features are reported, never silently dropped."""
        return [Signalering("wfs_afgekapt", f"{typename}: {returned} van {matched} objecten opgehaald.", "DOV WFS",
                            "Tabel onvolledig; verhoog max_features of verklein de straal.", severity="info")
                for typename, returned, matched in self.wfs.truncations]

    def figures(self) -> None:
        fig_dir = self.out / "figuren"
        for c in self.result.cpts:
            if c.profile and c.profile.depth_m:
                self.result.figures[f"cpt_{c.permkey}"] = self._relative(
                    cpt_figure.plot_cpt(c, fig_dir / f"cpt_{c.permkey}.png"))
        for b in self.result.boreholes:
            if b.lithology:
                self.result.figures[f"boring_{b.permkey}"] = self._relative(
                    borehole_column.plot_borehole(b, fig_dir / f"boring_{b.permkey}.png"))
        for model, vb in self.result.virtual_boreholes.items():
            self.result.figures[f"vb_{model}"] = self._relative(
                vb_column.plot_virtual_borehole(vb, fig_dir / f"vb_{model}.png"))
        if self.result.section and (self.result.section.boreholes or self.result.section.profile):
            self.result.figures["section"] = self._relative(
                section_figure.plot_section(self.result.section, fig_dir / "section.png"))
        self.log.info(f"{len(self.result.figures)} figuren geschreven in {fig_dir}")

    def run(self) -> StudyResult:
        stages = [
            ("Sonderingen", catalogue.DOV_WFS_URL, self.cpts, 0.15),
            ("Boringen", catalogue.DOV_WFS_URL, self.boreholes, 0.30),
            ("Peilputten", catalogue.DOV_WFS_URL, self.groundwater, 0.40),
        ]
        for source, url, fn, frac in stages:
            self.progress(frac, source)
            self.guarded(source, url, fn)
        self.progress(0.5, "Virtuele boringen")
        self.virtual_boreholes()
        self.progress(0.6, "Doorsnede")
        self.guarded("Doorsnede (virtuele boringen langs de lijn)",
                     catalogue.VB_DOORPRIK_URL.format(model=self.s.model_section), self.section)
        self.progress(0.7, "Kaartfeiten")
        self.map_facts()
        self.progress(0.85, "Signaleringen")
        self.result.signaleringen = checks.run_all(self.result) + self._truncation_signals()
        self.progress(0.9, "Figuren")
        self.guarded("Figuren", "", self.figures)
        (self.out / "data").mkdir(parents=True, exist_ok=True)
        self.result.write_json(self.out / "data" / "studie.json")
        self.progress(1.0, "Klaar")
        self.log.info(f"klaar: {self.result.summary()}")
        return self.result


def run(zone: StudyZone, settings: Settings, client, out_dir: Path, progress: Optional[Progress] = None,
        log: Optional[Log] = None) -> StudyResult:
    return _Runner(zone, settings, client, Path(out_dir), progress, log or Log("study")).run()
