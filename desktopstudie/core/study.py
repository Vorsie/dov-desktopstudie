"""Orchestrates one desktop study: fetch -> parse -> section -> facts -> figures -> checks -> JSON.
Every stage is guarded: a failure becomes a Provenance(ok=False) and the run continues. Inside a
stage every item is guarded too, so one unreachable fiche costs that fiche and nothing else."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from . import catalogue, checks, geometry, parallel
from .figures import borehole_column, cpt_figure, section_figure, vb_column
from .logging_util import Log
from .model import (
    Borehole,
    Cpt,
    GwFilter,
    MapFact,
    Provenance,
    Section,
    Signalering,
    StudyResult,
    StudyZone,
)
from .section import build_section, section_line
from .services import dov_xml, wms_gfi
from .services.dov_wfs import DovWfs, feature_xy
from .services.virtuele_boring import fetch_virtual_borehole

Progress = Callable[[float, str], None]

MESSAGE_CHARS = 200  # a provenance message is a summary; the full text goes to the log
GFI_RING_SAMPLES = 8  # ring vertices asked about per GetFeatureInfo map, on top of the centre
# The two signals that come from the run itself rather than from `checks`: nothing in the result
# still says a WFS list was cut off or that doorprik points failed, so a second pass of the rules
# (the shell runs one once the relief is in) cannot rebuild them - it has to carry them over.
# One fiche out of a hundred: a short breath. Three full-minute waits on a record that is down
# cost the whole study its time, while the WFS query that fills a table keeps the patient default.
ITEM_TIMEOUT_S = 15.0
ITEM_RETRIES = 1
JSON_RELATIVE = "data/studie.json"
TRUNCATION_CODE = "wfs_afgekapt"
SECTION_CODE = "doorsnede_onvolledig"
ORCHESTRATOR_CODES = (TRUNCATION_CODE, SECTION_CODE)


# The same class under the name the rest of the code knows: `parallel.load_each` raises it from
# inside a batch, and `except StudyCancelled` has to catch exactly that.
StudyCancelled = parallel.Cancelled


class EmptySource(Exception):
    """A source answered, but with nothing usable in it - a doorprik outside the model, a section
    line with no geology along it. `guarded` records it as a failed source with this text as the
    message, so the report says WHAT is missing instead of naming an exception type."""


def has_geology(section: Section) -> bool:
    """True when there is something to draw: at least one profile column with layers, or at least
    one doorprik anchor with layers. Outside the model both are empty and the figure would be a
    blank frame that reads as 'no geology here' rather than 'nothing was found here'."""
    profile = section.profile
    if profile is not None and any(column.layers for column in profile.columns):
        return True
    return any(borehole.layers for borehole in section.boreholes)


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
    map_ids: Optional[List[str]] = None  # None = all enabled catalogue entries


def _now() -> str:
    return dt.datetime.now().astimezone().replace(microsecond=0).isoformat()


def _prop(props, key, cast=None):
    value = props.get(key)
    if value in (None, ""):
        return None
    return cast(value) if cast else value


class _Runner:
    def __init__(self, zone: StudyZone, settings: Settings, client, out_dir: Path,
                 progress: Optional[Progress], log: Log, should_cancel: Optional[Callable[[], bool]]):
        self.zone = zone
        self.s = settings
        self.client = client
        self.out = Path(out_dir)
        self.progress = progress or (lambda f, m: None)
        self.should_cancel = should_cancel or (lambda: False)
        self.log = log
        self.wfs = DovWfs(client, log=log.child("dov_wfs"))
        self.xml_log = log.child("dov_xml")  # one logger for the three per-item XML parsers
        self.result = StudyResult(zone=zone, created_at=_now())
        self.zone.radius_m = settings.radius_m

    # --- plumbing -----------------------------------------------------------------------
    def _raise_if_cancelled(self) -> None:
        if self.should_cancel():
            raise StudyCancelled("afgebroken door de gebruiker")

    def _step(self, fraction: float, message: str) -> None:
        """A stage boundary: the chance to stop, then the progress report."""
        self._raise_if_cancelled()
        self.progress(fraction, message)

    def guarded(self, source: str, url: str, fn: Callable[[], None]) -> None:
        try:
            fn()
            self.result.provenance.append(Provenance(source, url, _now(), True))
        except StudyCancelled:
            raise  # a cancelled run is not a broken source
        except EmptySource as exc:
            self.log.warning(f"{source}: {exc}")
            self.result.provenance.append(Provenance(source, url, _now(), False, str(exc)))
        except Exception as exc:  # noqa: BLE001 - isolate every source
            self.log.warning(f"{source} niet beschikbaar: {exc}")
            self.result.provenance.append(
                Provenance(source, url, _now(), False, f"{type(exc).__name__}: {str(exc)[:MESSAGE_CHARS]}"))

    def _load_each(self, items: Sequence[Any], load_one: Callable[[Any], None], label: str,
                   max_workers: Optional[int] = None) -> int:
        """`parallel.load_each` with this run's workers, log and cancellation."""
        return parallel.load_each(items, load_one, label, max_workers or self.s.max_workers,
                                  self.log, self.should_cancel)

    def _item(self, url: str) -> bytes:
        """One per-item fetch (a fiche, an interpretation record): short timeout, one retry."""
        return self.client.get(url, timeout=ITEM_TIMEOUT_S, retries=ITEM_RETRIES)

    def dist(self, x: float, y: float) -> float:
        return geometry.distance_to_ring((x, y), self.zone.ring)

    def _relative(self, path: Path) -> str:
        """Figure paths in the JSON are relative to the output directory and use forward slashes,
        so a result written on Windows still resolves on another machine."""
        return Path(path).relative_to(self.out).as_posix()

    def _note_municipality(self, feats: Iterable[dict]) -> None:
        """The zone's municipality, from the NEAREST feature that names one. A WFS answer is
        unordered, so 'the first feature with a gemeente' can just as easily name a town on the far
        edge of the search radius. The first stage that finds one wins; later stages leave it be."""
        if self.result.municipality:
            return
        named = [(self.dist(*feature_xy(f)), f["properties"].get("gemeente")) for f in feats]
        named = [(distance, name) for distance, name in named if name]
        if not named:
            self.log.debug("geen gemeente genoemd in de features van deze bron")
            return
        self.result.municipality = min(named)[1]

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
        self._note_municipality(feats)
        nearest = [c for c in out if c.url][: self.s.n_cpt_figures]

        def load(c: Cpt) -> None:
            c.profile = dov_xml.parse_cpt_profile(self._item(c.url + ".xml"), log=self.xml_log)

        failed = self._load_each(nearest, load, "sondering")
        self.log.info(f"{len(out)} sonderingen binnen {self.s.radius_m:.0f} m, "
                      f"{len(nearest) - failed} opgehaald, {failed} mislukt")

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
        self._note_municipality(feats)
        nearest = [b for b in out if b.interpretation_url][: self.s.n_borehole_figures]

        def load(b: Borehole) -> None:
            b.lithology = dov_xml.parse_lithology(self._item(b.interpretation_url + ".xml"),
                                                  log=self.xml_log)

        failed = self._load_each(nearest, load, "lithologie")
        self.log.info(f"{len(out)} boringen, {sum(1 for b in out if b.interpretation_url)} met lithologie, "
                      f"{len(nearest) - failed} opgehaald, {failed} mislukt")

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
        self._note_municipality(feats)
        nearest = [g for g in out if g.levels_to and g.url][: self.s.n_gw_levels]

        def load(g: GwFilter) -> None:
            levels = dov_xml.parse_groundwater_levels(self._item(g.url + ".xml"), log=self.xml_log)
            g.latest = levels[-1] if levels else None

        failed = self._load_each(nearest, load, "peilmeting")
        self.log.info(f"{len(out)} peilputten, {len(nearest) - failed} opgehaald, {failed} mislukt, "
                      f"{sum(1 for g in out if g.latest)} met laatste peil")

    def virtual_boreholes(self) -> None:
        cx, cy = self.zone.representative_point  # inside the zone, also for L-shaped parcels
        log = self.log.child("virtuele_boring")

        def fetch(model: str) -> None:
            borehole = fetch_virtual_borehole(self.client, cx, cy, model, log=log)
            if not borehole.layers:
                raise EmptySource("geen lagen op dit punt (buiten het model?)")
            self.result.virtual_boreholes[model] = borehole

        for model in self.s.models_centroid:
            self.guarded(f"Virtuele boring {model}", catalogue.VB_DOORPRIK_URL.format(model=model),
                         lambda m=model: fetch(m))

    def section(self) -> None:
        if self.zone.section_line is None:
            self.zone.section_line = section_line(self.zone, self.s.section_extension_m)
        section = build_section(
            self.client, self.zone.section_line, self.zone, self.result.cpts, self.result.boreholes,
            self.result.gw_filters, self.s.n_section_points, self.s.corridor_m, self.s.model_section,
            log=self.log.child("section"), max_workers=self.s.max_workers, with_profile=self.s.with_profile)
        # The dense profile is a source of its own: losing it costs the fine columns and leaves
        # only the handful of anchors, which the reader has to be told about. Not reported when
        # the caller asked for no profile at all - nothing was tried, so nothing failed.
        if self.s.with_profile and section.profile is None:
            self.result.provenance.append(Provenance(
                "Doorsnede - profielbevraging", catalogue.VB_PROFILE_URL.format(model=self.s.model_section),
                _now(), False, "profiel niet beschikbaar; alleen doorprik-ankers"))
        if not has_geology(section):
            raise EmptySource("geen modellagen langs de lijn")
        self.result.section = section

    def _gfi_points(self) -> List[Tuple[float, float]]:
        """Where to ask a GetFeatureInfo map about the zone: the representative point plus ring
        vertices spread over the WHOLE ring. Taking the first eight vertices would sample one short
        arc of a buffered circle, so a flood zone touching the far side would never be asked about."""
        ring = self.zone.ring
        step = max(1, len(ring) // GFI_RING_SAMPLES)
        return [self.zone.representative_point] + list(ring[::step][:GFI_RING_SAMPLES])

    def _gfi_rows(self, entry: catalogue.MapEntry) -> List[dict]:
        """The GetFeatureInfo rows of one map, asked at every sample point at once.

        The points are independent queries against the same service, so they go out in parallel;
        the answers are merged back IN POINT ORDER, because a report whose table rows change place
        between two runs of the same study reads as a different answer.
        """
        gfi_log = self.log.child("wms_gfi")
        points = self._gfi_points()
        per_point: Dict[int, List[dict]] = {}

        def ask(numbered) -> None:
            index, (x, y) = numbered
            per_point[index] = wms_gfi.feature_info_at_point(self.client, entry.wms_url, entry.wms_layer,
                                                             x, y, log=gfi_log)

        self._load_each(list(enumerate(points)), ask, f"{entry.id} (GetFeatureInfo)")
        rows: List[dict] = []
        seen = set()
        for index in range(len(points)):
            for row in per_point.get(index, []):
                key = tuple(str(row.get(k)) for k in entry.fact_fields)
                if key not in seen:
                    seen.add(key)
                    rows.append({k: row.get(k) for k in entry.fact_fields})
        return rows

    def _fact_rows(self, entry: catalogue.MapEntry) -> List[dict]:
        if entry.fact_mode == "wfs":
            feats = self.wfs.intersecting(entry.wfs_typename, self.zone.wkt, self.s.max_features)
            return [{k: f["properties"].get(k) for k in entry.fact_fields} for f in feats]
        return self._gfi_rows(entry)

    def map_facts(self) -> None:
        """The facts of every map in the zone: fetched in parallel, recorded in catalogue order.

        Two things have to survive the thread pool. Each map keeps failing on its own - one WFS
        that is down costs that map's table, not the chapter - and the provenance keeps the order
        of the catalogue, so the sources chapter does not shuffle itself between two runs of the
        same study. Hence the split: the threads only fetch, the main thread records.
        """
        wanted = [e for e in catalogue.entries() if e.fact_mode is not None]
        if self.s.map_ids is not None:
            wanted = [e for e in wanted if e.id in self.s.map_ids]
        fetched: Dict[str, Any] = {}  # entry id -> rows, or the exception that explains their absence

        def fetch(entry: catalogue.MapEntry) -> None:
            try:
                fetched[entry.id] = self._fact_rows(entry)
            except StudyCancelled:
                raise
            except Exception as exc:  # noqa: BLE001 - kept for `guarded` to record below
                fetched[entry.id] = exc
                raise

        self._load_each(wanted, fetch, "kaartfeiten")
        for entry in wanted:
            outcome = fetched.get(entry.id, EmptySource("geen antwoord van de bron"))

            def record(e=entry, o=outcome) -> None:
                if isinstance(o, BaseException):
                    raise o
                self.result.map_facts.append(MapFact(e.id, e.title, o))
                self.log.debug(f"{e.id}: {len(o)} eenheden in de zone")

            url = entry.wms_url if entry.fact_mode == "gfi" else catalogue.DOV_WFS_URL
            self.guarded(f"{entry.title} (feiten)", url, record)

    def _truncation_signals(self) -> List[Signalering]:
        """WFS results cut off by max_features are reported, never silently dropped."""
        return [Signalering(TRUNCATION_CODE, f"{typename}: {returned} van {matched} objecten opgehaald.", "DOV WFS",
                            "Tabel onvolledig; verhoog max_features of verklein de straal.", severity="info")
                for typename, returned, matched in self.wfs.truncations]

    def _section_signals(self) -> List[Signalering]:
        """Doorprik points along the section line that failed. A section drawn from fewer columns
        than were asked for is thinner than it looks, and the gap in it reads as an absence of
        geology unless the count is stated."""
        section = self.result.section
        if section is None or section.failed_points <= 0:
            return []
        asked = section.failed_points + len(section.boreholes)
        return [Signalering(SECTION_CODE,
                            f"{section.failed_points} van {asked} doorprik-punten mislukt.",
                            "DOV virtuele boring",
                            "Doorsnede onvolledig; de kolommen op die punten ontbreken.", severity="info")]

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
        if self.result.section is not None and has_geology(self.result.section):
            self.result.figures["section"] = self._relative(
                section_figure.plot_section(self.result.section, fig_dir / "section.png"))
        self.log.info(f"{len(self.result.figures)} figuren geschreven in {fig_dir}")

    def write_json(self) -> None:
        path = self.out / "data" / "studie.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        self.result.write_json(path)

    def run(self) -> StudyResult:
        stages = [
            ("Sonderingen", catalogue.DOV_WFS_URL, self.cpts, 0.15),
            ("Boringen", catalogue.DOV_WFS_URL, self.boreholes, 0.30),
            ("Peilputten", catalogue.DOV_WFS_URL, self.groundwater, 0.40),
        ]
        for source, url, fn, frac in stages:
            self._step(frac, source)
            self.guarded(source, url, fn)
        self._step(0.5, "Virtuele boringen")
        self.virtual_boreholes()
        self._step(0.6, "Doorsnede")
        self.guarded("Doorsnede (virtuele boringen langs de lijn)",
                     catalogue.VB_DOORPRIK_URL.format(model=self.s.model_section), self.section)
        self._step(0.7, "Kaartfeiten")
        self.map_facts()
        # Figures before the checks: a figures stage that fell over is a failed source like any
        # other, and check_sources can only report it once it is in the provenance.
        self._step(0.85, "Figuren")
        self.guarded("Figuren", "", self.figures)
        self._step(0.92, "Signaleringen")
        all_signals = checks.run_all(self.result) + self._truncation_signals() + self._section_signals()
        self.result.signaleringen = checks.validate(all_signals)
        self.guarded("studie.json", JSON_RELATIVE, self.write_json)
        self._step(1.0, "Klaar")
        self.log.info(f"klaar: {self.result.summary()}")
        return self.result


def orchestrator_signals(result: StudyResult) -> List[Signalering]:
    """The signals in `result` that only this module could have produced.

    `checks.run_all` reads the result and rebuilds every rule-based signal from it, so a caller
    that re-runs the rules (the shell does, once the relief is measured) can throw the old list
    away - except for these two. A truncated WFS list and a failed doorprik leave no trace in the
    data itself, only in this run, so they are carried over rather than recomputed.
    """
    return [signal for signal in result.signaleringen if signal.code in ORCHESTRATOR_CODES]


def run(zone: StudyZone, settings: Settings, client, out_dir: Path, progress: Optional[Progress] = None,
        log: Optional[Log] = None, should_cancel: Optional[Callable[[], bool]] = None) -> StudyResult:
    """Run one study and write it to `out_dir`.

    `zone` is filled in as the run goes: `zone.radius_m` is set from the settings and
    `zone.section_line` is set to the computed default when the caller left it empty - the caller's
    own object is updated, so the shell can draw exactly the line that was used.

    `should_cancel` is polled between stages and around every per-item fetch; when it returns True
    the run raises `StudyCancelled` and writes no JSON.
    """
    return _Runner(zone, settings, client, Path(out_dir), progress, log or Log("study"), should_cancel).run()
