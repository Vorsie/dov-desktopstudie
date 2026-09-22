"""Builds the report tree (chapters -> pages) from a StudyResult. No rendering here; the QGIS
shell turns MapPage/FigurePage/TablePage/TextPage into layout pages.

A coded map carries more than one page. "Legenda voor de zone" is the legend the reader actually
needs - the handful of classes inside the zone instead of the hundreds on the full sheet, and the
ONLY table for that map - and it travels ON the map page (`MapPage.zone_legend`), printed under
the map frame, because a sheet holding two legend rows is a sheet of white paper. The "Leeswijzer"
behind it says how to read those codes (`MapEntry.reading_guide`). The quartair map adds the drawings DOV
publishes - those drawings ARE its legend - but this module fetches nothing: the shell hands the
files it already downloaded in through `build_report(..., report_images=...)`, keyed by
`profieltype:<code>` and `kaartblad:<nn>`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple, Union

from . import catalogue, lithology
from .catalogue import MODEL_TITLES
from .model import StudyResult, facts_of, plain_reason
from .services.http import short_url

FACT_DECIMALS = 2  # what a measured depth, thickness or standard deviation is worth on paper
# A service answers a yes/no field with a boolean, and a Dutch table that prints "Risico-inrichting:
# True" is printing Python at a reader. The words, not the literals.
BOOLEAN_WORDS = {True: "ja", False: "nee"}

# Why one sounding is drawn and another is not. The rule itself lives in `study.for_figures`.
# A note on the table, not a page of its own: four lines alone on a sheet is the loose item the
# packing exists to clear away, and the reader meets the rule where the soundings are listed.
FIGURE_CHOICE = (
    "Niet elke sondering hieronder krijgt een diagram: voor de figuren krijgen de elektrische "
    "sonderingen voorrang, hoe ver ze ook liggen, en pas daarna de dichtstbijzijnde mechanische. "
    "Een continu elektrische sondering meet de conusweerstand over de volledige diepte; een "
    "discontinu mechanische meet met stappen en mist wat daartussen ligt.")

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
    # Where the scale changes class, as (position 0..1, label). A bar whose classes are not of
    # equal width - the groundwater depths run 0..5 in steps of one and then 10, 15, 20 - is only
    # readable with its boundaries written under it, and a value may never be interpolated along
    # such a bar. Empty for a bar that is linear between its two ends.
    ticks: List[Tuple[float, str]] = field(default_factory=list)


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
    # The service's own GetLegendGraphic, relative to the output directory, for a map that is a
    # field of classes. Empty means the shell did not get it, and then no colours are drawn at
    # all: a key painted from guessed colours would not match the map above it.
    class_key: str = ""


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


# A sentence in a reading guide that describes the table under it. When there is no table, such a
# sentence promises the reader something the sheet does not hold, so it is left out.
TABLE_SENTENCE = re.compile(r"(?:De|Deze) (?:tabel|kolom|kolommen) ")


def _rows_note(rows_src: Optional[List[Dict[str, Any]]],
               entry: Optional[catalogue.MapEntry] = None) -> str:
    """Why a table is empty. An unreachable source must never read as an empty zone: "geen
    kaarteenheden" about a flood map that is down would tell the reader there is no flood risk.

    For a hazard map an empty answer IS the answer - the zone is not in flood-prone land - so the
    map says it in its own words (`MapEntry.empty_meaning`) instead of in the generic one.
    """
    if rows_src is None:
        return "Bron niet beschikbaar."
    if rows_src:
        return ""
    return (entry.empty_meaning if entry and entry.empty_meaning
            else "Geen kaarteenheden binnen de zone.")


def _without_table_sentences(guide: str) -> str:
    """The guide with the sentences about its table taken out, for a map that prints none."""
    kept = [part for part in re.split(r"(?<=\.)\s+", guide) if not TABLE_SENTENCE.match(part)]
    return " ".join(kept)


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
        # A measured value arrives as a double: the GxG service answers 2.8499999046325684 metres.
        # Printed in full it is unreadable and claims a precision nobody has, so a float gets the
        # two decimals a depth or a thickness is worth. What the service sent stays in the JSON.
        if isinstance(raw, bool):  # before any number: a bool IS an int in Python
            raw = BOOLEAN_WORDS[raw]
        cell = f"{label} [{raw}]" if label else _s(raw, FACT_DECIMALS if isinstance(raw, float) else None)
        out.append(short_url(cell) if cell.startswith("http") else cell)
    return out


# --- reading guide and zone legend ----------------------------------------------------------------

LINK = re.compile(r"https?://\S+")


def _guide_html(entry: catalogue.MapEntry, guide: Optional[str] = None) -> str:
    """The reading guide as one paragraph, with its URL made clickable.

    The URL lives in the guide text itself (one field per map, `MapEntry.reading_guide`) and points
    at the DOV page that carries the whole legend - all four were checked live on 2026-09-16.
    """
    return "<p>" + LINK.sub(lambda m: f'<a href="{m.group(0)}">{m.group(0)}</a>',
                            entry.reading_guide if guide is None else guide) + "</p>"


def _guide_text(entry: catalogue.MapEntry, has_rows: bool = True) -> Optional[TextPage]:
    """How to read this map's codes, or None for a map that needs no explaining.

    It rides along on the map page (`MapPage.guide`); a map without a guide simply carries none,
    which is the difference between a shorter map frame and an empty one. When the map prints no
    table, the sentences that describe one go with it: a guide that explains the columns of a
    table nobody can see reads as a missing page.
    """
    if not entry.reading_guide:
        return None
    guide = entry.reading_guide if has_rows else _without_table_sentences(entry.reading_guide)
    if not guide:
        return None
    return TextPage(f"Leeswijzer - {entry.title}", _guide_html(entry, guide))


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
    """How `report_images` names the header strip of one profile type."""
    return f"{PROFILE_KEY}:{code}"


def sheet_image_key(sheet: str) -> str:
    """How `report_images` names the units table of one map sheet."""
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
    rows_src = facts_of(result, entry.id)
    entries: List[LegendEntry] = []
    for row in rows_src or []:
        code = _s(row.get(QUARTAIR_CODE))
        if any(existing.code == code for existing in entries):
            continue
        entries.append(LegendEntry(code, quartair_sheet(code),
                                   images.get(profile_image_key(code), "")))
    return LegendPage(f"Legenda voor de zone - {entry.title}", entries, _rows_note(rows_src, entry))


ISOPACH_ID = "quartair_dikte"
# The thickness a contour of the isopach map carries, as the service spells it.
THICKNESS_FIELD = "Dikte_Quartair_m"
QUARTAIR_UNIT = "quartair"


def _point_name(row: Optional[Dict[str, Any]]) -> str:
    """How to name the sample point a row came from: the representative point, or which vertex.

    The GetFeatureInfo points are the representative point plus vertices of the zone's ring. When
    point 0 answers nothing its row is dropped and some other point leads the list - so the name
    has to be read off the row, never assumed.
    """
    index = (row or {}).get(catalogue.POINT_FIELD)
    if index is None or index == catalogue.REPRESENTATIVE_POINT:
        return "het representatieve punt"
    return f"punt {index} op de rand van de zone"


def _quartair_model_layer(result: StudyResult):
    """De Quartairlaag die het periodemodel op het representatieve punt geeft, of None."""
    borehole = result.virtual_boreholes.get("g3dv3_P")
    layers = [layer for layer in (borehole.layers if borehole else [])
              if layer.name.lower().startswith(QUARTAIR_UNIT)]
    return layers[0] if layers else None


def _isopach_note(result: StudyResult, rows: Optional[List[Dict[str, Any]]],
                  entry: catalogue.MapEntry) -> str:
    """The one line the thickness map still needs under it.

    The service draws the thickness ON the contours, so a table of distances to those same lines
    says nothing a reader cannot read off the map - it is gone. What the map cannot show is the
    modelled thickness at this exact point, so that stays, named as a model value because it is a
    calculation and not a borehole. The two can disagree (G3Dv3 said 3,78 m where the map shows
    contours of 5 and 10 m around the zone); that difference is information for a geotechnician
    and it is neither hidden nor explained away here.
    """
    parts = []
    spread = sorted({float(row[THICKNESS_FIELD]) for row in rows or []
                     if row.get(THICKNESS_FIELD) is not None})
    if not spread and _quartair_model_layer(result) is not None:
        # No contour in view AND the thickness already stands in the period table of chapter 4:
        # then this sheet has nothing of its own left to say. An empty page carrying one modelled
        # sentence reads as a fault, so the map drops out and lands on the bundled page at the
        # back. Where that table is missing, this sentence is the only thing still naming the
        # thickness and it stays.
        return ""
    if spread:
        seen = (f"{spread[0]:.1f} tot {spread[-1]:.1f} m" if spread[0] != spread[-1]
                else f"{spread[0]:.1f} m")
        parts.append(f"Isopachen in beeld: {seen} dikte Quartair, met de waarde op de lijn zelf.")
    layer = _quartair_model_layer(result)
    if layer is not None:
        parts.append(f"Modelwaarde G3Dv3 op het representatieve punt: {layer.thickness_m:.2f} m "
                     f"Quartair ({layer.top_mtaw:.2f} tot {layer.base_mtaw:.2f} mTAW). "
                     f"Een modelwaarde, geen boring.")
    return " ".join(parts)


def legend_shows_rows(legend) -> bool:
    """Whether a map page's zone legend actually shows something.

    A `LegendPage` carries `entries`, a `TablePage` carries `rows`, and `None` carries neither;
    the three callers that ask this question (the guide sentence, the bundled page of empty
    legends, and the shell's check for a sheet with nothing on it) must agree, and two of them
    stand on either side of the core/shell boundary.
    """
    return bool(getattr(legend, "rows", None) or getattr(legend, "entries", None))


def _zone_legend_for(entry: catalogue.MapEntry, result: StudyResult,
                     images: Dict[str, str]) -> Union[TablePage, LegendPage]:
    """The classes that lie inside the zone, once each.

    Deduplicated on the printed cells: the WFS answers with one row per map polygon, so the same
    soil type comes back as often as the zone crosses it, and a legend that repeats itself is a
    legend the reader stops reading.
    """
    if entry.id == QUARTAIR_ID:
        return _quartair_zone_legend(entry, result, images)
    rows_src = facts_of(result, entry.id)
    if entry.id == ISOPACH_ID:
        # No table at all: the thickness is printed on the lines by the service's own style, and a
        # column of distances to lines the reader can see is furniture, not an answer. Decided
        # before the cells are formatted, because none of them is ever printed.
        note = _isopach_note(result, rows_src, entry) or _rows_note(rows_src, entry)
        return TablePage(entry.title, [], [], note)
    fields, headers = _zone_legend_columns(entry)
    rows: List[List[str]] = []
    for row in rows_src or []:
        cells = _cells(entry, row, fields)  # `_cells` already prints a bare URL in its short form
        if cells not in rows:
            rows.append(cells)
    if entry.ramp:
        # A continuous field has no "classes in the zone": every sample point answers with its own
        # number, and nine near-identical rows cost two sheets while saying nothing the first row
        # does not. The first is the representative point - the one the virtual borehole stands on
        # and the one the bar under the map names (`_gfi_points` asks it first).
        return TablePage(f"Waarde op {_point_name(next(iter(rows_src or []), None))} - "
                         f"{entry.title}", headers, rows[:1], _rows_note(rows_src, entry))
    return TablePage(f"Legenda voor de zone - {entry.title}", headers, rows, _rows_note(rows_src, entry))


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
    for row in facts_of(result, entry.id) or []:
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
CLASS_KEY = "klassensleutel"


def ramp_image_key(map_id: str) -> str:
    """How `report_images` names the colour strip the shell cut for one map."""
    return f"{RAMP_KEY}:{map_id}"


def class_key_image_key(map_id: str) -> str:
    """How `report_images` names the class key the shell fetched for one map."""
    return f"{CLASS_KEY}:{map_id}"


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


GXG_RAMP_TITLE = "Grondwaterstand (m onder maaiveld)"


def _gxg_level(entry: catalogue.MapEntry) -> str:
    """"GHG" or "GLG", read off the field the service answers with."""
    return entry.fact_fields[0].split("-", 1)[0]


def _gxg_ramp(entry: catalogue.MapEntry, result: StudyResult, images: Dict[str, str]) -> ColourRamp:
    """The groundwater bar under its map, with the depth measured at this point under it.

    The class boundaries are written out (`catalogue.GXG_DEPTH_TICKS`) because they are NOT evenly
    spaced in value while they are drawn at equal height: without them the middle of the bar reads
    as ten metres where it is five. For the same reason nothing is marked ON the bar - the number
    stands in the table above it, where it cannot be misread.

    The service answers in metres below ground level. A designer thinks in mTAW, so the depth is
    also given as a level - but only with a ground level that was actually measured, and with the
    assumption named: the zone's mean from the DHMV, not the height of this one point.
    """
    ticks = catalogue.GXG_DEPTH_TICKS
    steps = len(ticks) - 1
    path = images.get(ramp_image_key(entry.id), "")
    level = _gxg_level(entry)
    row = next(iter(facts_of(result, entry.id) or []), None)
    depth = row.get(entry.fact_fields[0]) if row else None
    if depth is None:
        summary = f"{level}: geen waarde op dit punt (zie hoofdstuk Bronnen)."
    else:
        summary = f"{level} op {_point_name(row)}: {float(depth):.2f} m onder maaiveld"
        if result.relief is not None:
            mean = result.relief[2]
            summary += (f"; met het gemiddelde maaiveld van de zone ({mean:.2f} mTAW) is dat "
                        f"ongeveer {mean - float(depth):.2f} mTAW")
        summary += "."
    return ColourRamp(GXG_RAMP_TITLE, f"{ticks[0]:.0f} m-mv", f"{ticks[-1]:.0f} m-mv", summary,
                      path, "" if path else DEM_RAMP_MISSING,
                      ticks=[(index / steps, f"{value:.0f}") for index, value in enumerate(ticks)])


def _ramp_for(entry: catalogue.MapEntry, result: StudyResult,
              images: Dict[str, str]) -> ColourRamp:
    """The colour bar of a map whose legend is a scale rather than a list of classes.

    Two kinds exist and a third would fall into `_gxg_ramp`, which reads `fact_fields[0]` and
    would raise an IndexError on a map that has none. Naming the two keeps that a clear failure
    at the catalogue rather than a crash halfway through a report.
    """
    if entry.id == DEM_MAP_ID:
        return _dem_ramp(result, images)
    if entry.fact_fields:
        return _gxg_ramp(entry, result, images)
    raise ValueError(f"kaart {entry.id} vraagt een kleurschaal maar heeft geen feitveld")


def _chapter_ligging(result: StudyResult, images: Dict[str, str]) -> Chapter:
    z = result.zone
    cx, cy = z.centroid
    rx, ry = z.representative_point
    ligging = Chapter(1, "Ligging en topografie",
                      _map_pages("ligging", result.map_ids, show_investigations=False))
    for page in ligging.pages:
        if isinstance(page, MapPage):
            entry = catalogue.by_id(page.map_id)
            if entry.ramp:
                page.ramp = _ramp_for(entry, result, images)
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


def _chapter_geologie(result: StudyResult, report_images: Dict[str, str]) -> Chapter:
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
                       note=entry.note)
        if entry.ramp:
            page.ramp = _ramp_for(entry, result, report_images)
        if entry.class_key:
            page.class_key = report_images.get(class_key_image_key(entry.id), "")
        if entry.fact_mode is not None:
            page.zone_legend = _zone_legend_for(entry, result, report_images)
        # An empty zone legend means the sheet holds no table for the guide to describe.
        page.guide = _guide_text(entry, legend_shows_rows(page.zone_legend)
                                 or entry.fact_mode is None)
        geo.pages.append(page)
        geo.pages.extend(_zone_legend_figures(entry, result, report_images))
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
    figured = [c for c in result.cpts if f"cpt_{c.permkey}" in result.figures]
    inv.pages.append(TablePage(
        f"Sonderingen binnen {z.radius_m:.0f} m",
        ["Nummer", "Afst. (m)", "Diepte (m)", "Datum", "Methode", "Conus", "Uitvoerder", "Opdracht",
         "DOV-fiche"],
        [[c.number, _s(c.distance_m, 0), _s(c.depth_m, 1), _s(c.date), _s(c.method), _s(c.cone), _s(c.contractor),
          _s(c.project), c.permkey] for c in result.cpts],
        note=FIGURE_CHOICE if figured else ("Geen sonderingen binnen de straal."
                                            if not result.cpts else ""),
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
    for c in figured:
        inv.pages.append(FigurePage(f"Sondering {c.number}", result.figures[f"cpt_{c.permkey}"],
                                    f"{c.distance_m:.0f} m van de zone - {c.url}"))
    for b in result.boreholes:
        key = f"boring_{b.permkey}"
        if key in result.figures:
            caption = f"{b.distance_m:.0f} m van de zone - {b.url}"
            remarks = lithology.summarise(lithology.notable_terms(b.lithology))
            if remarks:
                # What the description itself says, quoted: never what it means for the ground.
                caption += f" - Opmerkingen uit de beschrijving: {remarks}"
            inv.pages.append(FigurePage(f"Boring {b.number}", result.figures[key], caption))
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
        return f"fout: {plain_reason(entry.message)}"
    return f"ok - {plain_reason(entry.message)}" if entry.message else "ok"


# Provenance lines that describe what this study PRODUCED rather than what it consulted. They are
# recorded so a failed write is visible in the log and in studie.json; in a table headed
# "Geraadpleegde bronnen" they read as services that were queried, which they never were.
OWN_PRODUCTS = ("Figuren", "studie.json")


def _chapter_bronnen(result: StudyResult) -> Chapter:
    sources = Chapter(8, "Bronnen en licenties")
    # Short URL and date only: the stored provenance keeps the whole request (a DWITHIN filter
    # runs to hundreds of characters) and a timestamp to the second with a timezone offset. Neither
    # fits a table column, and a column that does not fit is a column the reader cannot use - the
    # service and the day are what it takes to find a source again.
    sources.pages.append(TablePage(
        "Geraadpleegde bronnen", ["Bron", "URL", "Opgehaald", "Status"],
        [[p.source, short_url(p.url), p.retrieved_at[:10], _status(p)]
         for p in result.provenance if p.source not in OWN_PRODUCTS]))
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
    names them there whatever happens here.

    What survives the drop is what still says something. The zone legend comes from the WFS and
    does not depend on the image, so it stays - with rows, or with the sentence that an empty
    answer IS the answer here. The reading guide does not: it explains how to read a map that is
    no longer in the report, and four lines about a vanished map cost a sheet of 1.4 % ink.

    A legend that says nothing does not travel at all: it is handed back so `_gather_empty_answers`
    can put its sentence on the one page at the back of the report where every "nothing here"
    stands together. What comes back from here is exactly those - the ones with rows stay.
    """
    handed_back: List[Tuple[str, str]] = []
    for chapter in chapters:
        kept: List[Page] = []
        orphans: List[Page] = []
        for page in chapter.pages:
            if isinstance(page, MapPage) and map_page_key(page) in unavailable:
                answer = _empty_answer(page)
                if answer is not None:
                    handed_back.append(answer)
                elif page.zone_legend is not None:
                    orphans.append(page.zone_legend)
                continue
            kept.append(page)
        chapter.pages = kept + orphans
    return handed_back


def _empty_answer(page: MapPage) -> Optional[Tuple[str, str]]:
    """(map title, the sentence) when this map's zone legend shows nothing at all, else None.

    "Nothing" means no rows and no legend entries, AND a note that is one of the generic answers
    `_rows_note` writes - the very sentence, asked of this map's own entry. A legend without rows
    but with something of its own to say (the isopach sheet names the thickness in view and the
    modelled value) is content, not an exception, and must never be swept up with these.
    """
    legend = page.zone_legend
    if legend is None or legend_shows_rows(legend):
        return None
    entry = catalogue.by_id(page.map_id)
    note = getattr(legend, "note", "")
    if entry is None or note not in (_rows_note([], entry), _rows_note(None, entry)):
        return None
    return entry.title, note


def _gather_empty_answers(chapters: List[Chapter],
                          handed_back: List[Tuple[str, str]]) -> Optional[TextPage]:
    """One page at the very back holding every "no data here", grouped by the answer itself.

    A stack of "Legenda voor de zone - X / Geen kaarteenheden binnen de zone" blocks in the middle
    of a chapter is the ugliest thing in the report and it says the same sentence five times. Each
    map keeps its own sheet; only the empty block under it goes, and its sentence comes here.
    Nothing is lost: the sources chapter still lists every map with its own status.
    """
    grouped: Dict[str, List[str]] = {}
    for title, note in handed_back:
        grouped.setdefault(note, []).append(title)
    for chapter in chapters:
        for page in chapter.pages:
            if not isinstance(page, MapPage):
                continue
            answer = _empty_answer(page)
            if answer is None:
                continue
            page.zone_legend = None
            grouped.setdefault(answer[1], []).append(answer[0])
    if not grouped:
        return None
    parts = [f"<p>{note} Geldt voor: {', '.join(titles)}.</p>"
             for note, titles in grouped.items()]
    return TextPage("Geen gegevens binnen de zone", "".join(parts))


def build_report(result: StudyResult, meta: ReportMeta,
                 report_images: Optional[Dict[str, str]] = None,
                 unavailable: Optional[Set[MapPageKey]] = None) -> Report:
    """The whole report tree. `report_images` is every picture the shell fetched that is report
    CONTENT rather than a legend sheet, keyed by what it belongs to: `profieltype:<code>` for a
    header strip, `kaartblad:<nn>` for a units table, `kleurschaal:<map id>` for a colour strip
    and `klassensleutel:<map id>` for a class key, as paths relative to the output directory (the
    same shape as `StudyResult.figures`). Without it a legend keeps its lines but shows no
    drawings.

    `unavailable` holds the `map_page_key`s whose map image did not come back - no coverage here,
    or a fetch that failed. Those pages are left out entirely; the shell knows them because it
    fetched the images before this tree was built for printing, and the sources chapter says per
    map what happened."""
    z = result.zone
    cx, cy = z.centroid
    rx, ry = z.representative_point
    images = report_images or {}
    chapters = [
        _chapter_ligging(result, images), _chapter_historisch(result.map_ids),
        _chapter_geologie(result, images),
        _chapter_virtuele_boring(result), _chapter_grondonderzoek(result), _chapter_doorsnede(result),
        _chapter_samenvatting(result), _chapter_bronnen(result),
    ]
    handed_back = _drop_unavailable(chapters, set(unavailable)) if unavailable else []
    gathered = _gather_empty_answers(chapters, handed_back)
    if gathered is not None:
        chapters[-1].pages.append(gathered)  # the sources chapter: the very back of the report
    return Report(title=f"Desktopstudie {meta.project}", chapters=chapters, meta={
        "project": meta.project, "project_number": meta.project_number, "author": meta.author,
        "company": meta.company, "logo_path": meta.logo_path, "address": _s(z.address),
        "municipality": _s(result.municipality), "zone_name": z.name, "created_at": result.created_at,
        "centroid": f"{cx:.1f} / {cy:.1f}", "representative_point": f"{rx:.1f} / {ry:.1f}",
        "disclaimer": DISCLAIMER})
