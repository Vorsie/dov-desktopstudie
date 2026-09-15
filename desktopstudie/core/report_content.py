"""Builds the report tree (chapters -> pages) from a StudyResult. No rendering here; the QGIS
shell turns MapPage/FigurePage/TablePage/TextPage into layout pages."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union

from . import catalogue
from .model import StudyResult
from .services.virtuele_boring import MODEL_TITLES

DISCLAIMER = (
    "<p>Deze desktopstudie verzamelt open data van DOV en geopunt op het moment van opmaak. "
    "Ze bevat geen eigen geologische interpretatie, geen berekeningen en geen ontwerp. "
    "Modellagen (G3Dv3, HCOV) zijn regionale modellen en vervangen geen terreinonderzoek.</p>")


@dataclass
class ReportMeta:
    project: str
    author: str
    company: str
    project_number: str = ""
    logo_path: str = ""


@dataclass
class MapPage:
    """A rendered catalogue map. `scale` is the target scale (1:scale); the shell actually draws
    at the larger (more zoomed-out) of `scale` and whatever scale is needed to fit
    `extent_factor` times the zone's extent, so a small zone is never shown at an unreadably
    tight crop."""
    map_id: str
    title: str
    legend: bool = False
    scale: int = 5000
    extent_factor: float = 3.0  # minimum extent as a multiple of the zone size
    show_investigations: bool = False
    show_section_line: bool = False
    note: str = ""


@dataclass
class FigurePage:
    title: str
    image_path: str
    caption: str = ""


@dataclass
class TablePage:
    title: str
    columns: List[str]
    rows: List[List[str]]
    note: str = ""
    links: Optional[List[str]] = None  # one URL per row, aligned with `rows`; None if not applicable


@dataclass
class TextPage:
    title: str
    html: str


Page = Union[MapPage, FigurePage, TablePage, TextPage]


@dataclass
class Chapter:
    number: int
    title: str
    pages: List[Page] = field(default_factory=list)


@dataclass
class Report:
    title: str
    meta: Dict[str, Any]
    chapters: List[Chapter]


def _s(value: Any, digits: Optional[int] = None) -> str:
    if value is None:
        return "-"
    if isinstance(value, float) and digits is not None:
        return f"{value:.{digits}f}"
    return str(value)


def _map_pages(chapter: str, **kw) -> List[Page]:
    return [MapPage(e.id, e.title, legend=e.legend, scale=e.scale, note=e.note, **kw)
            for e in catalogue.entries(chapter)]


def _fact_table_for(entry: catalogue.MapEntry, result: StudyResult) -> TablePage:
    rows_src = next((mf.rows for mf in result.map_facts if mf.map_id == entry.id), None)
    cols = list(entry.fact_fields)
    headers = [entry.field_labels.get(col, col) for col in cols]
    rows: List[List[str]] = []
    for row in rows_src or []:
        out = []
        for col in cols:
            raw = row.get(col)
            label = entry.value_labels.get(col, {}).get(str(raw))
            out.append(f"{label} [{raw}]" if label else _s(raw))
        rows.append(out)
    note = ("Geen kaarteenheden binnen de zone." if rows_src == []
            else ("Bron niet beschikbaar." if rows_src is None else ""))
    return TablePage(f"{entry.title} - eenheden in de zone", headers, rows, note)


def _chapter_ligging(result: StudyResult) -> Chapter:
    z = result.zone
    cx, cy = z.centroid
    rx, ry = z.representative_point
    ligging = Chapter(1, "Ligging en topografie", _map_pages("ligging", show_investigations=False))
    facts = [["Gemeente", _s(result.municipality)], ["Adres", _s(z.address)],
             ["Zwaartepunt (Lambert 72)", f"{cx:.1f} / {cy:.1f}"],
             ["Representatief punt (virtuele boring)", f"{rx:.1f} / {ry:.1f}"],
             ["Oppervlakte zone", f"{z.area_m2:.0f} m2"], ["Straal grondonderzoek", f"{z.radius_m:.0f} m"]]
    if result.relief:
        lo, hi, mean = result.relief
        facts.append(["Maaiveld (DHMV II) min / max / gem.", f"{lo:.2f} / {hi:.2f} / {mean:.2f} mTAW"])
    ligging.pages.append(TablePage("Kerngegevens ligging", ["Kenmerk", "Waarde"], facts))
    return ligging


def _chapter_historisch() -> Chapter:
    hist = Chapter(2, "Historische kaarten", _map_pages("historisch"))
    for e in catalogue.entries("historisch", enabled_only=False):
        if not e.enabled:
            hist.pages.append(TextPage(e.title, f"<p>Niet opgenomen: {e.note}</p>"))
    hist.pages.append(TextPage(
        "Manuele controle historische kaarten",
        "<p>Controleer op elke kaart: vroegere waterlopen, vijvers en moerassen; verdwenen bebouwing en "
        "funderingen; ophogingen, groeven en stortplaatsen; wijzigingen in perceelsstructuur. De plugin "
        "interpreteert geen beelden.</p>"))
    return hist


def _chapter_geologie(result: StudyResult) -> Chapter:
    geo = Chapter(3, "Geologie en bodem")
    for entry in catalogue.entries("geologie"):
        geo.pages.append(MapPage(entry.id, entry.title, legend=entry.legend, scale=entry.scale, note=entry.note))
        if entry.fact_mode is not None:
            geo.pages.append(_fact_table_for(entry, result))
    return geo


def _chapter_virtuele_boring(result: StudyResult) -> Chapter:
    vb = Chapter(4, "Virtuele boring")
    if not result.virtual_boreholes:
        vb.pages.append(TextPage("Virtuele boring", "<p>Virtuele boring niet beschikbaar (zie bronnen).</p>"))
        return vb
    for model, borehole in result.virtual_boreholes.items():
        rows = [[layer.name, _s(layer.top_mtaw, 2), _s(layer.base_mtaw, 2), _s(layer.thickness_m, 2), layer.texture]
                for layer in borehole.layers]
        vb.pages.append(TablePage(
            f"Virtuele boring op het representatieve punt in de zone - {MODEL_TITLES.get(model, model)}",
            ["Eenheid", "Top (mTAW)", "Basis (mTAW)", "Dikte (m)", "Textuur (DOV)"], rows))
        if f"vb_{model}" in result.figures:
            vb.pages.append(FigurePage(f"Kolom {MODEL_TITLES.get(model, model)}", result.figures[f"vb_{model}"]))
    return vb


def _chapter_grondonderzoek(result: StudyResult) -> Chapter:
    z = result.zone
    inv = Chapter(5, "Grondonderzoek DOV")
    inv.pages.append(MapPage("grb", "Overzicht beschikbaar grondonderzoek", scale=5000, extent_factor=1.0,
                             show_investigations=True, show_section_line=True))
    inv.pages.append(TablePage(
        f"Sonderingen binnen {z.radius_m:.0f} m",
        ["Nummer", "Afstand (m)", "Diepte (m)", "Datum", "Methode", "Conus", "Uitvoerder", "Opdracht", "DOV-fiche"],
        [[c.number, _s(c.distance_m, 0), _s(c.depth_m, 1), _s(c.date), _s(c.method), _s(c.cone), _s(c.contractor),
          _s(c.project), c.permkey] for c in result.cpts],
        note="Geen sonderingen binnen de straal." if not result.cpts else "",
        links=[c.url for c in result.cpts]))
    inv.pages.append(TablePage(
        f"Boringen binnen {z.radius_m:.0f} m",
        ["Nummer", "Afstand (m)", "Diepte (m)", "Datum", "Methode", "Doel", "Uitvoerder", "Lithologie",
         "DOV-fiche"],
        [[b.number, _s(b.distance_m, 0), _s(b.depth_m, 1), _s(b.date), _s(b.method), _s(b.purpose),
          _s(b.contractor), "ja" if b.lithology else "-", b.permkey] for b in result.boreholes],
        note="Geen boringen binnen de straal." if not result.boreholes else "",
        links=[b.url for b in result.boreholes]))
    inv.pages.append(TablePage(
        f"Peilputten binnen {z.radius_m:.0f} m",
        ["GW-ID/filter", "Afstand (m)", "Aquifer", "Filterbasis (m-mv)", "Laatste peil (mTAW)", "Datum", "Meetnet",
         "DOV-fiche"],
        [[f"{f.gw_id}/{f.filter_no}", _s(f.distance_m, 0), _s(f.aquifer), _s(f.filter_base_m, 1),
          _s(f.latest.level_mtaw, 2) if f.latest else "-", f.latest.date if f.latest else "-", _s(f.network),
          f.gw_id] for f in result.gw_filters],
        note="Geen peilputten binnen de straal." if not result.gw_filters else "",
        links=[f.url for f in result.gw_filters]))
    for c in result.cpts:
        key = f"cpt_{c.permkey}"
        if key in result.figures:
            inv.pages.append(FigurePage(f"Sondering {c.number}", result.figures[key],
                                        f"{c.distance_m:.0f} m van de zone - {c.url}"))
    for b in result.boreholes:
        key = f"boring_{b.permkey}"
        if key in result.figures:
            inv.pages.append(FigurePage(f"Boring {b.number}", result.figures[key],
                                        f"{b.distance_m:.0f} m van de zone - {b.url}"))
    return inv


def _chapter_doorsnede(result: StudyResult) -> Chapter:
    sec = Chapter(6, "Doorsnede")
    sec.pages.append(MapPage("grb", "Ligging van de doorsnedelijn", scale=5000, extent_factor=1.5,
                             show_section_line=True))
    if "section" in result.figures:
        sec.pages.append(FigurePage(
            "Geologische doorsnede uit virtuele boringen (G3Dv3)", result.figures["section"],
            "Modeldata van DOV; geen eigen interpretatie. Proeven binnen de corridor zijn loodrecht "
            "geprojecteerd."))
    else:
        sec.pages.append(TextPage("Doorsnede", "<p>Doorsnede niet beschikbaar (zie bronnen).</p>"))
    return sec


def _chapter_samenvatting(result: StudyResult) -> Chapter:
    summary = Chapter(7, "Samenvatting en aandachtspunten")
    counts = result.summary()
    summary.pages.append(TablePage("Feiten", ["Kenmerk", "Waarde"], [
        ["Sonderingen binnen straal", str(counts["n_cpts"])],
        ["Boringen binnen straal", str(counts["n_boreholes"])],
        ["Peilputten binnen straal", str(counts["n_gw_filters"])],
        ["Signaleringen", str(counts["n_signaleringen"])],
        ["Bronnen niet beschikbaar", str(counts["n_sources_failed"])]]))
    summary.pages.append(TablePage(
        "Signaleringen", ["Feit", "Bron", "Aandachtspunt", "Ernst"],
        [[s.fact, s.source, s.advice, s.severity] for s in result.signaleringen],
        note="Geen signaleringen." if not result.signaleringen else ""))
    summary.pages.append(TextPage("Beperkingen", DISCLAIMER))
    return summary


def _chapter_bronnen(result: StudyResult) -> Chapter:
    sources = Chapter(8, "Bronnen en licenties")
    sources.pages.append(TablePage(
        "Geraadpleegde bronnen", ["Bron", "URL", "Opgehaald", "Status"],
        [[p.source, p.url, p.retrieved_at, "ok" if p.ok else f"fout: {p.message}"] for p in result.provenance]))
    sources.pages.append(TablePage(
        "Kaartbronnen en licenties", ["Kaart", "Bron", "Licentie"],
        [[e.title, e.attribution, e.licence] for e in catalogue.entries()]))
    return sources


def build_report(result: StudyResult, meta: ReportMeta) -> Report:
    z = result.zone
    cx, cy = z.centroid
    rx, ry = z.representative_point
    chapters = [
        _chapter_ligging(result), _chapter_historisch(), _chapter_geologie(result),
        _chapter_virtuele_boring(result), _chapter_grondonderzoek(result), _chapter_doorsnede(result),
        _chapter_samenvatting(result), _chapter_bronnen(result),
    ]
    return Report(title=f"Desktopstudie {meta.project}", chapters=chapters, meta={
        "project": meta.project, "project_number": meta.project_number, "author": meta.author,
        "company": meta.company, "logo_path": meta.logo_path, "address": _s(z.address),
        "municipality": _s(result.municipality), "zone_name": z.name, "created_at": result.created_at,
        "centroid": f"{cx:.1f} / {cy:.1f}", "representative_point": f"{rx:.1f} / {ry:.1f}",
        "disclaimer": DISCLAIMER})
