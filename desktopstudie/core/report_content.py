"""Builds the report tree (chapters -> pages) from a StudyResult. No rendering here; the QGIS
shell turns MapPage/FigurePage/TablePage/TextPage into layout pages."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union

from . import catalogue
from .model import StudyResult
from .services.virtuele_boring import MODEL_TITLES


@dataclass
class ReportMeta:
    project: str
    author: str
    company: str
    project_number: str = ""
    logo_path: str = ""


@dataclass
class MapPage:
    map_id: str
    title: str
    legend: bool = False
    scale: int = 5000  # 1:scale, from the catalogue entry; the shell zooms out when the zone does not fit
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


def _fact_tables(result: StudyResult) -> List[Page]:
    pages: List[Page] = []
    for entry in catalogue.entries("geologie"):
        if entry.fact_mode is None:
            continue
        rows_src = next((mf.rows for mf in result.map_facts if mf.map_id == entry.id), None)
        cols = list(entry.fact_fields)
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
        pages.append(TablePage(f"{entry.title} - eenheden in de zone", cols, rows, note))
    return pages


def build_report(result: StudyResult, meta: ReportMeta) -> Report:
    z = result.zone
    cx, cy = z.centroid
    chapters: List[Chapter] = []

    ligging = Chapter(1, "Ligging en topografie", _map_pages("ligging", show_investigations=False))
    facts = [["Gemeente", _s(result.municipality)], ["Adres", _s(z.address)],
             ["Zwaartepunt (Lambert 72)", f"{cx:.1f} / {cy:.1f}"],
             ["Oppervlakte zone", f"{z.area_m2:.0f} m2"], ["Straal grondonderzoek", f"{z.radius_m:.0f} m"]]
    if result.relief:
        lo, hi, mean = result.relief
        facts.append(["Maaiveld (DHMV II) min / max / gem.", f"{lo:.2f} / {hi:.2f} / {mean:.2f} mTAW"])
    ligging.pages.append(TablePage("Kerngegevens ligging", ["Kenmerk", "Waarde"], facts))
    chapters.append(ligging)

    hist = Chapter(2, "Historische kaarten", _map_pages("historisch"))
    for e in catalogue.entries("historisch", enabled_only=False):
        if not e.enabled:
            hist.pages.append(TextPage(e.title, f"<p>Niet opgenomen: {e.note}</p>"))
    hist.pages.append(TextPage(
        "Manuele controle historische kaarten",
        "<p>Controleer op elke kaart: vroegere waterlopen, vijvers en moerassen; verdwenen bebouwing en "
        "funderingen; ophogingen, groeven en stortplaatsen; wijzigingen in perceelsstructuur. De plugin "
        "interpreteert geen beelden.</p>"))
    chapters.append(hist)

    geo = Chapter(3, "Geologie en bodem", _map_pages("geologie"))
    geo.pages.extend(_fact_tables(result))
    chapters.append(geo)

    vb = Chapter(4, "Virtuele boring")
    for model, borehole in result.virtual_boreholes.items():
        rows = [[layer.name, _s(layer.top_mtaw, 2), _s(layer.base_mtaw, 2), _s(layer.thickness_m, 2), layer.texture]
                for layer in borehole.layers]
        vb.pages.append(TablePage(
            f"Virtuele boring op het representatieve punt in de zone - {MODEL_TITLES.get(model, model)}",
            ["Eenheid", "Top (mTAW)", "Basis (mTAW)", "Dikte (m)", "Textuur (DOV)"], rows))
        if f"vb_{model}" in result.figures:
            vb.pages.append(FigurePage(f"Kolom {MODEL_TITLES.get(model, model)}", result.figures[f"vb_{model}"]))
    chapters.append(vb)

    inv = Chapter(5, "Grondonderzoek DOV")
    inv.pages.append(MapPage("grb", "Overzicht beschikbaar grondonderzoek", scale=5000, extent_factor=1.0,
                             show_investigations=True, show_section_line=True))
    inv.pages.append(TablePage(
        f"Sonderingen binnen {z.radius_m:.0f} m",
        ["Nummer", "Afstand (m)", "Diepte (m)", "Datum", "Methode", "Conus", "Uitvoerder", "Opdracht", "DOV"],
        [[c.number, _s(c.distance_m, 0), _s(c.depth_m, 1), _s(c.date), _s(c.method), _s(c.cone), _s(c.contractor),
          _s(c.project), c.url] for c in result.cpts]))
    inv.pages.append(TablePage(
        f"Boringen binnen {z.radius_m:.0f} m",
        ["Nummer", "Afstand (m)", "Diepte (m)", "Datum", "Methode", "Doel", "Uitvoerder", "Lithologie", "DOV"],
        [[b.number, _s(b.distance_m, 0), _s(b.depth_m, 1), _s(b.date), _s(b.method), _s(b.purpose),
          _s(b.contractor), "ja" if b.lithology else "-", b.url] for b in result.boreholes]))
    inv.pages.append(TablePage(
        f"Peilputten binnen {z.radius_m:.0f} m",
        ["GW-ID/filter", "Afstand (m)", "Aquifer", "Filterbasis (m-mv)", "Laatste peil (mTAW)", "Datum", "Meetnet",
         "DOV"],
        [[f"{f.gw_id}/{f.filter_no}", _s(f.distance_m, 0), _s(f.aquifer), _s(f.filter_base_m, 1),
          _s(f.latest.level_mtaw, 2) if f.latest else "-", f.latest.date if f.latest else "-", _s(f.network), f.url]
         for f in result.gw_filters]))
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
    chapters.append(inv)

    sec = Chapter(6, "Doorsnede")
    if "section" in result.figures:
        sec.pages.append(FigurePage(
            "Geologische doorsnede uit virtuele boringen (G3Dv3)", result.figures["section"],
            "Modeldata van DOV; geen eigen interpretatie. Proeven binnen de corridor zijn loodrecht "
            "geprojecteerd."))
    else:
        sec.pages.append(TextPage("Doorsnede", "<p>Doorsnede niet beschikbaar (zie bronnen).</p>"))
    chapters.append(sec)

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
    summary.pages.append(TextPage(
        "Beperkingen",
        "<p>Deze desktopstudie verzamelt open data van DOV en geopunt op het moment van opmaak. "
        "Ze bevat geen eigen geologische interpretatie, geen berekeningen en geen ontwerp. "
        "Modellagen (G3Dv3, HCOV) zijn regionale modellen en vervangen geen terreinonderzoek.</p>"))
    chapters.append(summary)

    sources = Chapter(8, "Bronnen en licenties")
    sources.pages.append(TablePage(
        "Geraadpleegde bronnen", ["Bron", "URL", "Opgehaald", "Status"],
        [[p.source, p.url, p.retrieved_at, "ok" if p.ok else f"fout: {p.message}"] for p in result.provenance]))
    sources.pages.append(TablePage(
        "Kaartbronnen en licenties", ["Kaart", "Bron", "Licentie"],
        [[e.title, e.attribution, e.licence] for e in catalogue.entries()]))
    chapters.append(sources)

    return Report(title=f"Desktopstudie {meta.project}", chapters=chapters, meta={
        "project": meta.project, "project_number": meta.project_number, "author": meta.author,
        "company": meta.company, "logo_path": meta.logo_path, "address": z.address,
        "municipality": result.municipality, "zone_name": z.name, "created_at": result.created_at,
        "centroid": f"{cx:.1f} / {cy:.1f}"})
