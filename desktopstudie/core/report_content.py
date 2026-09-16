"""Builds the report tree (chapters -> pages) from a StudyResult. No rendering here; the QGIS
shell turns MapPage/FigurePage/TablePage/TextPage into layout pages.

A coded map carries more than one page. The fact table says WHAT lies in the zone, the
"Leeswijzer" says how to read those codes (`MapEntry.reading_guide`), and "Legenda voor de zone"
is the legend the reader actually needs: the handful of classes inside the zone instead of the
hundreds on the full sheet. The quartair map adds a drawing per profile type - that drawing IS its
legend - but this module fetches nothing: the shell hands the files it already downloaded in
through `build_report(..., zone_legend_images=...)`, keyed by the URL the row carried.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from . import catalogue
from .catalogue import MODEL_TITLES
from .model import StudyResult
from .services.http import short_url

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
    """A picture on a sheet of its own, drawn as large as the content band allows."""
    title: str
    image_path: str
    caption: str = ""


@dataclass
class LegendEntry:
    """One class of a map legend: its code, the sheet it was mapped on, and the drawing DOV
    publishes for it. `image_path` is empty when the shell could not fetch that drawing - the line
    stays, because code and sheet are still true, and the sources chapter says what went wrong."""
    code: str
    sheet: str
    image_path: str = ""


@dataclass
class LegendPage:
    """The classes of one map inside the zone, each with its own drawing under its own label.

    A strip of three centimetres does not deserve a sheet of its own: four pages for two profile
    types (a table saying "see overleaf", two near-empty strips and the units table) is two too
    many. So the strips sit here, on the legend page, and the entries keep the code and the sheet
    as data - a reader gets the picture, a machine still gets the facts.
    """
    title: str
    entries: List[LegendEntry]
    note: str = ""


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


Page = Union[MapPage, FigurePage, LegendPage, TablePage, TextPage]


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
    """Every map of a chapter, each followed by its reading guide when it has one."""
    pages: List[Page] = []
    for entry in catalogue.entries(chapter):
        pages.append(MapPage(entry.id, entry.title, legend=entry.legend, scale=entry.scale,
                             note=entry.note, **kw))
        pages.extend(_guide_page(entry, []))
    return pages


def _fact_rows(entry: catalogue.MapEntry, result: StudyResult) -> Optional[List[Dict[str, Any]]]:
    """The rows the study found for this map: `[]` when the zone holds none, None when the source
    never answered. Telling those two apart is the whole point of keeping it Optional."""
    return next((mf.rows for mf in result.map_facts if mf.map_id == entry.id), None)


def _rows_note(rows_src: Optional[List[Dict[str, Any]]]) -> str:
    """Why a table is empty. An unreachable source must never read as an empty zone: "geen
    kaarteenheden" about a flood map that is down would tell the reader there is no flood risk."""
    if rows_src is None:
        return "Bron niet beschikbaar."
    return "Geen kaarteenheden binnen de zone." if not rows_src else ""


def _cells(entry: catalogue.MapEntry, row: Dict[str, Any], columns: Sequence[str]) -> List[str]:
    """One table row, with the catalogue's label in front of the raw token it translates.

    The raw token stays visible in square brackets: a reader who knows the service has to be able
    to check the translation without leaving the page. A cell that is a bare URL is printed short:
    a URL carries no spaces, so a table cannot wrap one - it fits or it is cut off mid-word, which
    is what the quartair drawing links did ("...DOV_Quartair_5000"). What the service sent stays
    in `MapFact.rows` and in studie.json.
    """
    out = []
    for col in columns:
        raw = row.get(col)
        label = entry.value_labels.get(col, {}).get(str(raw))
        cell = f"{label} [{raw}]" if label else _s(raw)
        out.append(short_url(cell) if cell.startswith("http") else cell)
    return out


def _fact_table_for(entry: catalogue.MapEntry, result: StudyResult) -> TablePage:
    rows_src = _fact_rows(entry, result)
    cols = list(entry.fact_fields)
    headers = [entry.field_labels.get(col, col) for col in cols]
    rows = [_cells(entry, row, cols) for row in rows_src or []]
    return TablePage(f"{entry.title} - eenheden in de zone", headers, rows, _rows_note(rows_src))


# --- reading guide and zone legend ----------------------------------------------------------------

# A row of the quartair map carries the URL of the drawing of its profile type; the 1/200 000 map
# carries the PDF of the whole legend. Where a row knows a better address than the fixed DOV page
# in the guide, the guide points there instead.
ROW_LEGEND_FIELDS = ("uitgebreide_legende", "legende")
LINK = re.compile(r"https?://\S+")


def _guide_html(entry: catalogue.MapEntry, rows: Sequence[Dict[str, Any]]) -> str:
    """The reading guide as one paragraph, with its URL made clickable.

    The guide is a fixed text per map, but a row can know a more precise address than the page the
    text names (the `uitgebreide_legende` PDF of the quartair sheets). When it does, that address
    replaces the one in the text: two links in three sentences is one too many, and the row's link
    is the more specific of the two.
    """
    text = entry.reading_guide
    row_link = next((str(row[key]) for row in rows for key in ROW_LEGEND_FIELDS
                     if row.get(key) and str(row[key]).lower().endswith(".pdf")), "")
    if row_link:
        text = LINK.sub(row_link, text)
    return "<p>" + LINK.sub(lambda m: f'<a href="{m.group(0)}">{m.group(0)}</a>', text) + "</p>"


def _guide_page(entry: catalogue.MapEntry, rows: Sequence[Dict[str, Any]]) -> List[Page]:
    """Zero or one TextPage: a map without a guide gets no empty sheet."""
    if not entry.reading_guide:
        return []
    return [TextPage(f"Leeswijzer - {entry.title}", _guide_html(entry, rows))]


# What "Legenda voor de zone" shows per map: (field, header). Not the fact fields, because the
# legend answers a different question than the fact table - it names the CLASS, not everything the
# service knows about the polygon it was found in. Maps that are not listed fall back to their own
# fact fields, which for a map of three columns is the same thing.
ZONE_LEGEND_COLUMNS: Dict[str, Tuple[Tuple[str, str], ...]] = {
    "bodemkaart": (("Bodemtype", "Bodemtype"), ("Bodemserie", "Serie"),
                   ("Beknopte_omschrijving_bodemserie", "Omschrijving"),
                   ("Textuurklasse", "Textuur"), ("Drainageklasse", "Drainage")),
    "tertiair": (("code", "Code"), ("formatie", "Formatie"), ("lid", "Lid"),
                 ("beschrijving", "Beschrijving")),
    # No quartair entry: that legend is not built from fact fields at all but from the code, its
    # map sheet and the drawing that follows it (`_quartair_zone_legend`).
}
QUARTAIR_ID = "quartair"
QUARTAIR_CODE, QUARTAIR_IMAGE = "profieltype", "legende"
# A DOV profile-type drawing has a fixed build: a header (colour swatch, letter code and one line
# of description) and, under it, the units table of the whole map sheet - the same table for every
# profile type of that sheet. The report therefore prints one header per profile type and the
# units table once, and the zone legend names the sheet instead of repeating a 145-character URL
# no reader can use.
QUARTAIR_SHEET_CHARS = 2
PROFILE_KEY, SHEET_KEY = "profieltype", "kaartblad"


def quartair_sheet(code: str) -> str:
    """The map sheet of a profile type: the first two digits of its code (22010 -> 22).

    A code shorter than that is its own sheet - the 1/200 000 map numbers its types 1, 3, 3a - so
    nothing is ever cut in half.
    """
    return code[:QUARTAIR_SHEET_CHARS] if len(code) > QUARTAIR_SHEET_CHARS else code


def profile_image_key(code: str) -> str:
    """How `zone_legend_images` names the header strip of one profile type."""
    return f"{PROFILE_KEY}:{code}"


def sheet_image_key(sheet: str) -> str:
    """How `zone_legend_images` names the units table of one map sheet."""
    return f"{SHEET_KEY}:{sheet}"


def _zone_legend_columns(entry: catalogue.MapEntry) -> Tuple[List[str], List[str]]:
    """(fields, headers) for the zone legend of one map."""
    chosen = ZONE_LEGEND_COLUMNS.get(entry.id)
    if chosen is None:
        fields = list(entry.fact_fields)
        return fields, [entry.field_labels.get(f, f) for f in fields]
    return [f for f, _h in chosen], [h for _f, h in chosen]


def _quartair_zone_legend(entry: catalogue.MapEntry, result: StudyResult,
                          images: Dict[str, str]) -> LegendPage:
    """Every profile type in the zone, with the header strip DOV draws for it.

    Not the legend URL the row carries: 145 characters of download link that a table cannot wrap
    and a reader of a printed report cannot use. The strip itself - colour swatch, letter code, one
    line of description - says what the URL was for. The raw URL stays in `MapFact.rows` and in
    studie.json.
    """
    rows_src = _fact_rows(entry, result)
    entries: List[LegendEntry] = []
    for row in rows_src or []:
        code = _s(row.get(QUARTAIR_CODE))
        if any(existing.code == code for existing in entries):
            continue
        entries.append(LegendEntry(code, quartair_sheet(code),
                                   images.get(profile_image_key(code), "")))
    return LegendPage(f"Legenda voor de zone - {entry.title}", entries, _rows_note(rows_src))


def _zone_legend_for(entry: catalogue.MapEntry, result: StudyResult,
                     images: Dict[str, str]) -> Union[TablePage, LegendPage]:
    """The classes that lie inside the zone, once each.

    Deduplicated on the printed cells: the WFS answers with one row per map polygon, so the same
    soil type comes back as often as the zone crosses it, and a legend that repeats itself is a
    legend the reader stops reading.
    """
    if entry.id == QUARTAIR_ID:
        return _quartair_zone_legend(entry, result, images)
    rows_src = _fact_rows(entry, result)
    fields, headers = _zone_legend_columns(entry)
    rows: List[List[str]] = []
    for row in rows_src or []:
        cells = _cells(entry, row, fields)  # `_cells` already prints a bare URL in its short form
        if cells not in rows:
            rows.append(cells)
    return TablePage(f"Legenda voor de zone - {entry.title}", headers, rows, _rows_note(rows_src))


def _zone_legend_figures(entry: catalogue.MapEntry, result: StudyResult,
                         images: Dict[str, str]) -> List[Page]:
    """The units table of every map sheet the zone touches, once each.

    That table is the same drawing for every profile type of its sheet, so printing it per type
    would be the same page three times over; the part that DOES differ per type is the header
    strip, and that one sits on the legend page above. A sheet whose drawing did not come back
    simply has no page.
    """
    if entry.id != QUARTAIR_ID or not images:
        return []
    pages: List[Page] = []
    seen = set()
    for row in _fact_rows(entry, result) or []:
        sheet = quartair_sheet(_s(row.get(QUARTAIR_CODE)))
        units = images.get(sheet_image_key(sheet))
        if units is None or sheet in seen:
            continue
        seen.add(sheet)
        pages.append(FigurePage(f"Eenheden op kaartblad {sheet}", units,
                                f"Eenheden van kaartblad {sheet}, geldig voor elk profieltype van "
                                f"dat blad - DOV"))
    return pages


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
        "interpreteert geen beelden.</p>"
        "<p>Beoordeel daarnaast het risico op conventionele en toxische explosieven (WOI/WOII): "
        "raadpleeg bommenkaart.be en, bij aanwijzingen, DOVO. Die bronnen zijn geen open data en "
        "zitten niet in deze studie.</p>"))
    return hist


def _chapter_geologie(result: StudyResult, zone_legend_images: Dict[str, str]) -> Chapter:
    """Per map: the map, what lies in the zone, how to read those codes, and the legend of the
    classes that are actually there - in the order the reader needs them."""
    geo = Chapter(3, "Geologie en bodem")
    for entry in catalogue.entries("geologie"):
        geo.pages.append(MapPage(entry.id, entry.title, legend=entry.legend, scale=entry.scale,
                                 note=entry.note))
        if entry.fact_mode is None:
            geo.pages.extend(_guide_page(entry, []))
            continue
        rows = _fact_rows(entry, result) or []
        geo.pages.append(_fact_table_for(entry, result))
        geo.pages.extend(_guide_page(entry, rows))
        geo.pages.append(_zone_legend_for(entry, result, zone_legend_images))
        geo.pages.extend(_zone_legend_figures(entry, result, zone_legend_images))
    return geo


def _chapter_virtuele_boring(result: StudyResult) -> Chapter:
    vb = Chapter(4, "Virtuele boring")
    # A model that answered with zero layers is not a virtual borehole: the point lies outside it.
    # Only a borehole WITH layers counts, otherwise the chapter shows empty tables where the reader
    # expects geology and reads them as "no geology here".
    if not any(borehole.layers for borehole in result.virtual_boreholes.values()):
        vb.pages.append(TextPage("Virtuele boring", "<p>Virtuele boring niet beschikbaar (zie bronnen).</p>"))
        return vb
    for model, borehole in result.virtual_boreholes.items():
        rows = [[layer.name, _s(layer.top_mtaw, 2), _s(layer.base_mtaw, 2), _s(layer.thickness_m, 2), layer.texture]
                for layer in borehole.layers]
        vb.pages.append(TablePage(
            f"Virtuele boring op het representatieve punt in de zone - {MODEL_TITLES.get(model, model)}",
            ["Eenheid", "Top (mTAW)", "Basis (mTAW)", "Dikte (m)", "Textuur (DOV)"], rows,
            note="" if rows else "Geen modellagen op dit punt."))
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
        ["Nummer", "Afst. (m)", "Diepte (m)", "Datum", "Methode", "Conus", "Uitvoerder", "Opdracht",
         "DOV-fiche"],
        [[c.number, _s(c.distance_m, 0), _s(c.depth_m, 1), _s(c.date), _s(c.method), _s(c.cone), _s(c.contractor),
          _s(c.project), c.permkey] for c in result.cpts],
        note="Geen sonderingen binnen de straal." if not result.cpts else "",
        links=[c.url for c in result.cpts]))
    inv.pages.append(TablePage(
        f"Boringen binnen {z.radius_m:.0f} m",
        ["Nummer", "Afst. (m)", "Diepte (m)", "Datum", "Methode", "Doel", "Uitvoerder", "Lithologie",
         "DOV-fiche"],
        [[b.number, _s(b.distance_m, 0), _s(b.depth_m, 1), _s(b.date), _s(b.method), _s(b.purpose),
          _s(b.contractor), "ja" if b.lithology else "-", b.permkey] for b in result.boreholes],
        note="Geen boringen binnen de straal." if not result.boreholes else "",
        links=[b.url for b in result.boreholes]))
    inv.pages.append(TablePage(
        f"Peilputten binnen {z.radius_m:.0f} m",
        ["GW-ID/filter", "Afst. (m)", "Aquifer", "Filterbasis (m-mv)", "Laatste peil (mTAW)", "Datum", "Meetnet",
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
    # Short URL and date only: the stored provenance keeps the whole request (a DWITHIN filter
    # runs to hundreds of characters) and a timestamp to the second with a timezone offset. Neither
    # fits a table column, and a column that does not fit is a column the reader cannot use - the
    # service and the day are what it takes to find a source again.
    sources.pages.append(TablePage(
        "Geraadpleegde bronnen", ["Bron", "URL", "Opgehaald", "Status"],
        [[p.source, short_url(p.url), p.retrieved_at[:10], "ok" if p.ok else f"fout: {p.message}"]
         for p in result.provenance]))
    sources.pages.append(TablePage(
        "Kaartbronnen en licenties", ["Kaart", "Bron", "Licentie"],
        [[e.title, e.attribution, e.licence] for e in catalogue.entries()]))
    return sources


def build_report(result: StudyResult, meta: ReportMeta,
                 zone_legend_images: Optional[Dict[str, str]] = None) -> Report:
    """The whole report tree. `zone_legend_images` maps the legend URL of a quartair row to the
    image the shell fetched for it, as a path relative to the output directory (the same shape as
    `StudyResult.figures`); without it those figure pages are simply left out."""
    z = result.zone
    cx, cy = z.centroid
    rx, ry = z.representative_point
    chapters = [
        _chapter_ligging(result), _chapter_historisch(),
        _chapter_geologie(result, zone_legend_images or {}),
        _chapter_virtuele_boring(result), _chapter_grondonderzoek(result), _chapter_doorsnede(result),
        _chapter_samenvatting(result), _chapter_bronnen(result),
    ]
    return Report(title=f"Desktopstudie {meta.project}", chapters=chapters, meta={
        "project": meta.project, "project_number": meta.project_number, "author": meta.author,
        "company": meta.company, "logo_path": meta.logo_path, "address": _s(z.address),
        "municipality": _s(result.municipality), "zone_name": z.name, "created_at": result.created_at,
        "centroid": f"{cx:.1f} / {cy:.1f}", "representative_point": f"{rx:.1f} / {ry:.1f}",
        "disclaimer": DISCLAIMER})
