"""Builds the report tree (chapters -> pages) from a StudyResult. No rendering here; the QGIS
shell turns MapPage/FigurePage/TablePage/TextPage into layout pages.

A coded map carries more than one page. "Legenda voor de zone" is the legend the reader actually
needs - the handful of classes inside the zone instead of the hundreds on the full sheet, and the
ONLY table for that map - and it travels ON the map page (`MapPage.zone_legend`), printed under
the map frame, because a sheet holding two legend rows is a sheet of white paper. The "Leeswijzer"
behind it says how to read those codes (`MapEntry.reading_guide`). The quartair map adds the drawings DOV
publishes - those drawings ARE its legend - but this module fetches nothing: the shell hands the
files it already downloaded in through `build_report(..., zone_legend_images=...)`, keyed by
`profieltype:<code>` and `kaartblad:<nn>`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple, Union

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
class ColourRamp:
    """A map's continuous colour scale, printed as a strip under that map.

    For a scale that runs over the whole of Flanders - the height model runs from -50 to 300 mTAW
    while a building plot spans a few metres - a legend page says almost nothing and a strip under
    the map says it all: what the colours mean, and where this zone lies on them (`summary`).

    `image_path` is the strip the shell cut from the service's own GetLegendGraphic, relative to
    the output directory. Empty means the strip did not come back, and then NO colours are drawn:
    a ramp painted from guessed colours would not match the map above it.

    `band` says where this zone lies ON the scale, as two fractions of the strip (0 = the left
    end, 1 = the right end), and that is what makes the strip say anything at all: over a range of
    350 metres a building plot is one shade of one colour. A zone of four metres is a millimetre
    of paper, too narrow for a bracket, so `mean_at` carries the fallback - one mark at the mean -
    and the shell picks between them, because only the shell knows how wide the strip is printed.
    """
    title: str
    low: str  # what the left end of the strip means
    high: str  # what the right end means
    summary: str  # the zone's own values, in one line
    image_path: str = ""
    note: str = ""
    band: Optional[Tuple[float, float]] = None  # (minimum, maximum) of the zone, 0..1
    band_label: str = ""
    mean_at: Optional[float] = None  # the mean of the zone, 0..1
    mean_label: str = ""


@dataclass
class MapPage:
    """A rendered catalogue map. `scale` is the target scale (1:scale); the shell actually draws
    at the larger (more zoomed-out) of `scale` and whatever scale is needed to fit
    `extent_factor` times the zone's extent, so a small zone is never shown at an unreadably
    tight crop.

    `guide` (how to read this map's codes) and `zone_legend` (the classes of THIS map inside the
    zone) travel WITH the map instead of on pages of their own: four lines of text or two legend
    rows on an A4 is a sheet of white paper. The shell prints them directly under the map frame,
    guide first, and shrinks that frame by exactly what they need; what still does not fit runs on
    to the next sheet.
    """
    map_id: str
    title: str
    legend: bool = False
    scale: int = 5000
    extent_factor: float = 3.0  # minimum extent as a multiple of the zone size
    show_investigations: bool = False
    show_section_line: bool = False
    note: str = ""
    guide: Optional[TextPage] = None
    zone_legend: Optional[Page] = None
    ramp: Optional[ColourRamp] = None


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


def _map_pages(chapter: str, only: Optional[List[str]] = None, **kw) -> List[Page]:
    """Every CHOSEN map of a chapter, each carrying its reading guide when it has one.

    `only` is `StudyResult.map_ids`: a map the user unchecked never got fetched, so a sheet for it
    would print "Bron niet beschikbaar" - the same sentence a service that was down gets. It has
    to be absent, not empty.
    """
    return [MapPage(entry.id, entry.title, legend=entry.legend, scale=entry.scale,
                    note=entry.note, guide=_guide_text(entry), **kw)
            for entry in catalogue.entries(chapter, only=only)]


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


# --- reading guide and zone legend ----------------------------------------------------------------

LINK = re.compile(r"https?://\S+")


def _guide_html(entry: catalogue.MapEntry) -> str:
    """The reading guide as one paragraph, with its URL made clickable.

    The URL lives in the guide text itself (one field per map, `MapEntry.reading_guide`) and points
    at the DOV page that carries the whole legend - all four were checked live on 2026-09-16.
    """
    return "<p>" + LINK.sub(lambda m: f'<a href="{m.group(0)}">{m.group(0)}</a>',
                            entry.reading_guide) + "</p>"


def _guide_text(entry: catalogue.MapEntry) -> Optional[TextPage]:
    """How to read this map's codes, or None for a map that needs no explaining.

    It rides along on the map page (`MapPage.guide`); a map without a guide simply carries none,
    which is the difference between a shorter map frame and an empty one.
    """
    if not entry.reading_guide:
        return None
    return TextPage(f"Leeswijzer - {entry.title}", _guide_html(entry))


# What "Legenda voor de zone" shows per map: (field, header). Not the fact fields, because the
# legend answers a different question than the fact table - it names the CLASS, not everything the
# service knows about the polygon it was found in. Maps that are not listed fall back to their own
# fact fields, which for a map of three columns is the same thing.
ZONE_LEGEND_COLUMNS: Dict[str, Tuple[Tuple[str, str], ...]] = {
    # "Gegeneraliseerde_legende" ("Antropogeen") says something no other column says, so it comes
    # along now that the fact table is gone; the texture and drainage CODES only spell out the
    # column beside them and are left out.
    "bodemkaart": (("Bodemtype", "Bodemtype"), ("Bodemserie", "Serie"),
                   ("Beknopte_omschrijving_bodemserie", "Omschrijving"),
                   ("Textuurklasse", "Textuur"), ("Drainageklasse", "Drainage"),
                   ("Gegeneraliseerde_legende", "Legende")),
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


# The one map whose legend is a continuous colour scale instead of a list of classes. Its
# GetLegendGraphic is a ramp over the whole height range of Flanders; a page for that is a page
# the reader turns past, a strip under the map is what it is worth (`ColourRamp`).
DEM_MAP_ID = "dhmv_dtm"
DEM_RAMP_TITLE = "Hoogte maaiveld (m TAW)"
DEM_RAMP_MISSING = "Kleurschaal niet opgehaald; zie de leeswijzer hierna."
RAMP_KEY = "kleurschaal"


def ramp_image_key(map_id: str) -> str:
    """How `zone_legend_images` names the colour strip the shell cut for one map."""
    return f"{RAMP_KEY}:{map_id}"


def _ramp_at(value: float, low: float, high: float) -> float:
    """Where a height falls on the strip: 0 at the left end, 1 at the right.

    Clamped on purpose. A zone above or below what the service's own scale covers would otherwise
    be marked off the paper, and a mark beside the strip says nothing at all.
    """
    if high <= low:
        return 0.0
    return min(1.0, max(0.0, (value - low) / (high - low)))


def _dem_ramp(result: StudyResult, images: Dict[str, str]) -> ColourRamp:
    """The height model's colour scale, with this zone marked on it and its three heights under it.

    The ends are the service's (`catalogue.DHMV_RAMP_MTAW`); the values are what the shell measured
    over the zone (`StudyResult.relief`, min/max/mean). A zone that was never measured - a service
    that was down, a zone outside the model - says so, and is marked nowhere: a tick without a
    number behind it would suggest a measurement nobody made.
    """
    low, high = catalogue.DHMV_RAMP_MTAW
    path = images.get(ramp_image_key(DEM_MAP_ID), "")
    ramp = ColourRamp(DEM_RAMP_TITLE, f"{low:.0f} mTAW", f"{high:.0f} mTAW",
                      "Zone: geen hoogtewaarden gemeten (zie hoofdstuk Bronnen).", path,
                      "" if path else DEM_RAMP_MISSING)
    if result.relief is None:
        return ramp
    lo, hi, mean = result.relief
    ramp.summary = (f"Zone: laagste {lo:.2f} - gemiddeld {mean:.2f} - hoogste {hi:.2f} mTAW "
                    f"(DHMV II, zonale statistiek)")
    ramp.band = (_ramp_at(lo, low, high), _ramp_at(hi, low, high))
    ramp.band_label = f"zone {lo:.2f} - {hi:.2f} mTAW"
    ramp.mean_at = _ramp_at(mean, low, high)
    ramp.mean_label = f"zone gemiddeld {mean:.2f} mTAW"
    return ramp


def _chapter_ligging(result: StudyResult, images: Dict[str, str]) -> Chapter:
    z = result.zone
    cx, cy = z.centroid
    rx, ry = z.representative_point
    ligging = Chapter(1, "Ligging en topografie",
                      _map_pages("ligging", result.map_ids, show_investigations=False))
    for page in ligging.pages:
        if isinstance(page, MapPage) and page.map_id == DEM_MAP_ID:
            page.ramp = _dem_ramp(result, images)
    facts = [["Gemeente", _s(result.municipality)], ["Adres", _s(z.address)],
             ["Zwaartepunt (Lambert 72)", f"{cx:.1f} / {cy:.1f}"],
             ["Representatief punt (virtuele boring)", f"{rx:.1f} / {ry:.1f}"],
             ["Oppervlakte zone", f"{z.area_m2:.0f} m2"], ["Straal grondonderzoek", f"{z.radius_m:.0f} m"]]
    if result.relief:
        lo, hi, mean = result.relief
        facts.append(["Maaiveld (DHMV II) min / max / gem.", f"{lo:.2f} / {hi:.2f} / {mean:.2f} mTAW"])
    ligging.pages.append(TablePage("Kerngegevens ligging", ["Kenmerk", "Waarde"], facts))
    return ligging


def _chapter_historisch(only: Optional[List[str]] = None) -> Chapter:
    """The chosen historical maps, and the manual check that belongs with them.

    The maps that are switched off get no sheet here. A page saying "Niet opgenomen" between the
    historical maps tells the reader nothing the sources chapter does not tell better, and for the
    bombs it said twice over what the manual check below says once.
    """
    hist = Chapter(2, "Historische kaarten", _map_pages("historisch", only))
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
    """Per map: the map, with how to read its codes and the classes that lie in the zone printed
    under it.

    Both ride along on the map page (`MapPage.guide`, `MapPage.zone_legend`) rather than following
    it on sheets of their own: four lines of leeswijzer and one or two legend rows each used to
    cost a whole A4. Only the quartair units table of a map sheet stays a page, because that one
    is a drawing of half an A4.

    One table per map, not two. The fact table and the zone legend used to say the same thing -
    the same soil type on two sheets, and for the quartair map a column of download links no
    reader can use - so the legend, which is the deduplicated one with the drawings, replaced it.
    `MapFact.rows` in studie.json still carry every row exactly as the service gave them.
    """
    geo = Chapter(3, "Geologie en bodem")
    for entry in catalogue.entries("geologie", only=result.map_ids):
        page = MapPage(entry.id, entry.title, legend=entry.legend, scale=entry.scale,
                       note=entry.note, guide=_guide_text(entry))
        if entry.fact_mode is not None:
            page.zone_legend = _zone_legend_for(entry, result, zone_legend_images)
        geo.pages.append(page)
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
    # Where the borehole was taken, per model. The centroid and the representative point stand in
    # chapter 1, but those are properties of the ZONE; this is the point the model was actually
    # asked about, and two models can answer from a different cell and a different ground level.
    vb.pages.append(TablePage(
        "Plaats van de virtuele boringen",
        ["Model", "X (Lambert 72)", "Y (Lambert 72)", "Maaiveld (mTAW)", "Lagen"],
        [[MODEL_TITLES.get(model, model), _s(borehole.x, 1), _s(borehole.y, 1),
          _s(borehole.surface_mtaw, 2), str(len(borehole.layers))]
         for model, borehole in result.virtual_boreholes.items()]))
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


def _status(entry) -> str:
    """What the sources table says about one source.

    A source can answer perfectly well and still have nothing to show here - a historical mosaic
    without a sheet for this town. That is "ok" with a reason, not a failure, and the reason has to
    reach the page or the reader is left with a blank map and no explanation.
    """
    if not entry.ok:
        return f"fout: {entry.message}"
    return f"ok - {entry.message}" if entry.message else "ok"


def _chapter_bronnen(result: StudyResult) -> Chapter:
    sources = Chapter(8, "Bronnen en licenties")
    # Short URL and date only: the stored provenance keeps the whole request (a DWITHIN filter
    # runs to hundreds of characters) and a timestamp to the second with a timezone offset. Neither
    # fits a table column, and a column that does not fit is a column the reader cannot use - the
    # service and the day are what it takes to find a source again.
    sources.pages.append(TablePage(
        "Geraadpleegde bronnen", ["Bron", "URL", "Opgehaald", "Status"],
        [[p.source, short_url(p.url), p.retrieved_at[:10], _status(p)] for p in result.provenance]))
    sources.pages.append(TablePage(
        "Kaartbronnen en licenties", ["Kaart", "Bron", "Licentie"],
        [[e.title, e.attribution, e.licence] for e in catalogue.entries(only=result.map_ids)]))
    # What the study could NOT look at, and why. Here rather than between the maps themselves: a
    # reader who misses a map looks it up in the sources, and a sheet per absent map is a sheet
    # about nothing. The reason is the catalogue's own note, written for a reader.
    left_out = [entry for entry in catalogue.entries(enabled_only=False) if not entry.enabled]
    if left_out:
        sources.pages.append(TablePage(
            "Niet opgenomen kaarten", ["Kaart", "Reden"],
            [[entry.title, entry.note] for entry in left_out]))
    return sources


MapPageKey = Tuple[str, int, float, bool, bool]


def map_page_key(page: MapPage) -> MapPageKey:
    """What decides which map image a page needs: the map plus the framing it asks for.

    The shell plans one image per key (`layout.plan_map_images` computes the very same extent from
    the very same fields), so it can hand back the keys it found no image for. Per FRAMING, not
    per map: the GRB base map carries three, and a mosaic may well cover the narrow frame and not
    the wide one.
    """
    return (page.map_id, page.scale, page.extent_factor, page.show_investigations,
            page.show_section_line)


def _drop_unavailable(chapters: List[Chapter], unavailable: Set[MapPageKey]) -> None:
    """Take out the map pages whose image never arrived, and keep what did not depend on it.

    A sheet with an empty frame and a line saying why is a sheet the reader turns past; the
    sources chapter is where "geen dekking op deze locatie" and a failed fetch belong, and it
    names them there whatever happens here. The reading guide is catalogue text and the zone
    legend comes from the WFS - neither depends on the image - so both survive the drop, back on
    sheets of their own in the order they had under the map, since there is no map left to print
    them under.
    """
    for chapter in chapters:
        kept: List[Page] = []
        for page in chapter.pages:
            if isinstance(page, MapPage) and map_page_key(page) in unavailable:
                kept.extend(part for part in (page.guide, page.zone_legend) if part is not None)
                continue
            kept.append(page)
        chapter.pages = kept


def build_report(result: StudyResult, meta: ReportMeta,
                 zone_legend_images: Optional[Dict[str, str]] = None,
                 unavailable: Optional[Set[MapPageKey]] = None) -> Report:
    """The whole report tree. `zone_legend_images` maps `profieltype:<code>` to the header strip,
    `kaartblad:<nn>` to the units table and `kleurschaal:<map id>` to a colour strip the shell
    fetched, as paths relative to the output directory (the same shape as `StudyResult.figures`);
    without it the legend keeps its lines but shows no drawings.

    `unavailable` holds the `map_page_key`s whose map image did not come back - no coverage here,
    or a fetch that failed. Those pages are left out entirely; the shell knows them because it
    fetched the images before this tree was built for printing, and the sources chapter says per
    map what happened."""
    z = result.zone
    cx, cy = z.centroid
    rx, ry = z.representative_point
    images = zone_legend_images or {}
    chapters = [
        _chapter_ligging(result, images), _chapter_historisch(result.map_ids),
        _chapter_geologie(result, images),
        _chapter_virtuele_boring(result), _chapter_grondonderzoek(result), _chapter_doorsnede(result),
        _chapter_samenvatting(result), _chapter_bronnen(result),
    ]
    if unavailable:
        _drop_unavailable(chapters, set(unavailable))
    return Report(title=f"Desktopstudie {meta.project}", chapters=chapters, meta={
        "project": meta.project, "project_number": meta.project_number, "author": meta.author,
        "company": meta.company, "logo_path": meta.logo_path, "address": _s(z.address),
        "municipality": _s(result.municipality), "zone_name": z.name, "created_at": result.created_at,
        "centroid": f"{cx:.1f} / {cy:.1f}", "representative_point": f"{rx:.1f} / {ry:.1f}",
        "disclaimer": DISCLAIMER})
