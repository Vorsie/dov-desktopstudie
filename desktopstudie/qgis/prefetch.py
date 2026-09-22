"""Everything a report needs off the network, fetched before a single sheet is drawn.

This is the worker half of the shell. `pipeline.prepare` runs it on a `QgsTask`, and the reason
it is a module of its own is exactly that: an import of `prefetch` says "no QGIS layer, no
project, no widget" where an import of `layout` said nothing of the kind. Everything here is HTTP
and files - `urllib` through the study's own `HttpClient`, `QImage` for the pixels, `Path` for
what lands on disk.

Three batches go out, each isolated per item and each polling the caller's cancel flag
(`parallel.load_each`).

*The legends.* One GetLegendGraphic per map that asks for one, plus the colour strips the report
prints under a map instead of on a sheet of its own.

*The quartair drawings.* Not a GetLegendGraphic at all but files from a document portal, which
answers with its own web page often enough that the bytes have to be checked - see
`_drawing_bytes`.

*The map images.* One GetMap per (map, framing) instead of letting the WMS provider pull tiles
while each of ninety sheets renders; that was 312 s of a 607 s study. The framing comes from
`layout` - the planner and the page have to agree to the metre, so both ask `layout.page_image` -
and the pictures land as PNG plus world file for `layers.snapshot_layer` to draw.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Set, Tuple

from qgis.core import QgsRectangle
from qgis.PyQt.QtGui import QImage

from ..core import catalogue, parallel
from ..core.catalogue import BASE_MAP_ID, MapEntry
from ..core.model import StudyResult
from ..core.report_content import (
    QUARTAIR_CODE,
    QUARTAIR_ID,
    QUARTAIR_IMAGE,
    MapPage,
    Report,
    profile_image_key,
    quartair_sheet,
    sheet_image_key,
)
from ..core.services.dov_portal import PNG_MAGIC, content_link, says_not_found
from ..core.services.http import DATA_DIR, HttpClient, HttpError, build_url
from .export import PDF_DPI
from .images import (
    ZONE_LEGEND_PREFIX,
    crop_profile_header,
    crop_sheet_units,
    is_empty,
    load_tile,
    over_backdrop,
    ramp_strip,
)
from .layers import CRS_AUTHID
from .layout import MAP_H, MAP_W, page_image

# Where the fetched pictures land, under the study's output folder.
LEGEND_DIR = "legendas"
MAP_IMAGE_DIR = "kaarten"
RAMP_SUFFIX = "_schaal"
# How many of each batch are in flight at once. A legend is a stamp and a map image is a full
# sheet, so the second batch may be wider without asking more of the service per second.
LEGEND_WORKERS = 4
MAP_IMAGE_WORKERS = 8
# One legend out of a batch, same reasoning as a fiche in the core: a short breath, because three
# full-minute waits on a service that is down cost the report every legend page behind it.
LEGEND_TIMEOUT_S = 15.0
# Een profieltypetekening is geen GetLegendGraphic-stempel maar een bestand uit een documentportaal
# - 168 kB is normaal - en op een trage dag haalt dat de vijftien seconden hierboven niet. Ruimer,
# maar begrensd: twee pogingen van dertig seconden is de bovengrens die een run nog draaglijk houdt.
DRAWING_TIMEOUT_S = 30.0
LEGEND_RETRIES = 1
# How often a drawing is asked for. The download links of the dataset portal answer with HTTP 200
# and the portal's own web page instead of the file now and then (live 2026-09-16, the same URL
# gave the PNG minutes earlier), and that answer is not an error the HTTP client can see - so the
# bytes are checked here and a bad answer is asked again, past the cache.
ZONE_LEGEND_TRIES = 2
# One GetMap per map page, fetched up front and in parallel. Asked at exactly the size the page
# prints it, so nothing is up- or downscaled on paper; capped at what a service will hand out in
# one request.
MAP_IMAGE_DPI = PDF_DPI
MAP_IMAGE_MAX_PX = 4096
# A full-page GetMap is a hundred times the work of a 64 px probe, so it gets a longer breath than
# a legend - but one retry only: the page can be printed without its background.
MAP_IMAGE_TIMEOUT_S = 30.0
MAP_IMAGE_RETRIES = 1


# --- the legends and the colour strips --------------------------------------------------------

def wms_legend_url(entry: MapEntry, options: str = "") -> str:
    """The GetLegendGraphic URL for one catalogue entry.

    STYLE travels with it: a legend drawn from the layer default while the map is drawn with a
    named style shows classes the map does not have (gxg is exactly that case). LEGEND_OPTIONS is
    a GeoServer extension that lays the classes out in columns; services that do not know it
    ignore it.
    """
    params = {"SERVICE": "WMS", "VERSION": "1.3.0", "REQUEST": "GetLegendGraphic",
              "FORMAT": "image/png", "LAYER": entry.wms_layer, "STYLE": entry.wms_style}
    if options:
        params["LEGEND_OPTIONS"] = options
    return build_url(entry.wms_url, params)


def fetch_legend(entry: MapEntry, out_dir, client: HttpClient, log=None) -> Optional[Path]:
    """Fetch one legend to `out_dir/legendas/<map_id>.png`, or None with a WARNING."""
    url = wms_legend_url(entry, entry.legend_options)
    try:
        data = client.get(url, timeout=LEGEND_TIMEOUT_S, retries=LEGEND_RETRIES)
    except HttpError as exc:
        if log:
            log.warning(f"Legenda van {entry.id} niet opgehaald: {exc}")
        return None
    if not data:
        if log:
            log.warning(f"Legenda van {entry.id} kwam leeg terug")
        return None
    path = Path(out_dir) / LEGEND_DIR / f"{entry.id}.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def fetch_ramp(entry: MapEntry, out_dir, client: HttpClient, log=None) -> Optional[Path]:
    """The colour strip of one map, cut from that map's own GetLegendGraphic.

    Report content, not a legend page: the height model's legend is a ramp over the whole of
    Flanders, which fills a sheet with a picture of three centimetres. Under the map, next to the
    three heights measured over the zone, the same picture says everything it has to say.
    """
    legend = fetch_legend(entry, out_dir, client, log)
    if legend is None:
        return None
    strip = ramp_strip(legend, Path(legend).with_name(f"{entry.id}{RAMP_SUFFIX}.png"),
                       flip=entry.ramp_low_at_top)
    if strip is None and log:
        log.warning(f"Kleurschaal van {entry.id}: geen herkenbare kleurbalk in de legenda")
    return strip


def prepare_legends(entries: Sequence[MapEntry], out_dir, client: HttpClient,
                    log=None, should_cancel: Optional[Callable[[], bool]] = None
                    ) -> Tuple[Dict[str, Path], List[MapEntry]]:
    """(map_id -> legend PNG, entries that came back without one).

    Fetched here rather than by the layout so that one failing service costs one legend page, not
    the report, and so the shell can run this phase with its own progress and cancellation. The
    legends are independent downloads from several services, so they go out in parallel;
    each still fails on its own, and the caller gets the misses back to record as failed sources.

    The client comes from the caller, always: one study has one disk cache and one cache mode
    (`http.study_client`), and a client built here would quietly be a second one that ignores the
    mode the user chose.
    """
    out_dir = Path(out_dir)
    wanted = [entry for entry in entries if entry.legend]
    images: Dict[str, Path] = {}

    def fetch(entry: MapEntry) -> None:
        path = fetch_legend(entry, out_dir, client, log)
        if path is not None:
            images[entry.id] = path

    parallel.load_each(wanted, fetch, "legenda", LEGEND_WORKERS, log, should_cancel)
    missing = [entry for entry in wanted if entry.id not in images]
    if log:
        log.info(f"Legendas opgehaald: {len(images)}/{len(wanted)}")
        if missing:
            log.warning(f"Geen legenda voor: {', '.join(entry.id for entry in missing)}")
    return images, missing


# --- the drawings behind the zone legend ------------------------------------------------------

def zone_legend_targets(result: StudyResult) -> Dict[str, str]:
    """URL -> profile type, one entry per distinct drawing the quartair rows point at.

    The WFS answers with a row per map polygon, so a zone crossing the same profile type twice
    carries the same URL twice; fetching it twice would cost the service two requests for one file.
    """
    targets: Dict[str, str] = {}
    for fact in result.map_facts:
        if fact.map_id != QUARTAIR_ID:
            continue
        for row in fact.rows:
            url, code = str(row.get(QUARTAIR_IMAGE) or ""), str(row.get(QUARTAIR_CODE) or "")
            if url.startswith("http") and code and url not in targets:
                targets[url] = code
    return targets


class NoDrawingPublished(Exception):
    """Het portaal antwoordt met een niet-gevonden-pagina: DOV publiceert hier geen tekening.

    Een eigen fout en geen `HttpError`, want het is geen storing. De lezer krijgt er een andere
    zin bij: een feit over de bron in plaats van een uitnodiging om het nog eens te proberen.
    """


def _drawing_bytes(client: HttpClient, url: str, code: str, log=None) -> bytes:
    """One profile-type drawing, or an HttpError saying what came back instead.

    The URL ends in "_png" but is a download link into a document portal, and that portal answers
    with its own web page - HTTP 200, text/html - often enough that one answer proves nothing. The
    bytes are therefore checked here. Een pagina wordt niet bewaard en niet klakkeloos herhaald:
    ze draagt de directe link naar het bestand in zich, en die wordt gevolgd.
    """
    # The first try may come straight from the disk cache - which is the point: a web page cached
    # by an earlier run is exactly what has to be noticed. Every try after it goes past the cache,
    # so a bad cached answer costs one request, not none and not two.
    for attempt in range(ZONE_LEGEND_TRIES):
        data = client.get(url, timeout=DRAWING_TIMEOUT_S, retries=LEGEND_RETRIES,
                          cache_mode="refresh" if attempt else None)
        if data.startswith(PNG_MAGIC):
            return data
        # Geen bestand, dus niets om te bewaren: anders dient de cache deze pagina bij elke
        # volgende run zonder netwerk weer op.
        client.forget(url)
        if says_not_found(data):
            # Niet nog eens proberen: deze pagina zegt dat het document niet bestaat, en een
            # tweede poging levert dezelfde pagina op.
            if log:
                log.info(f"Profieltype {code}: het portaal publiceert hiervoor geen tekening")
            raise NoDrawingPublished(code)
        if log:
            log.warning(f"Profieltype {code}: antwoord {attempt + 1}/{ZONE_LEGEND_TRIES} is geen PNG "
                        f"({len(data)} bytes)")
        link = content_link(data, url)
        if link:
            if log:
                log.info(f"Profieltype {code}: de pagina wijst naar het bestand zelf, die link volgen")
            found = client.get(link, timeout=DRAWING_TIMEOUT_S, retries=LEGEND_RETRIES)
            if found.startswith(PNG_MAGIC):
                return found
            client.forget(link)
            if log:
                log.warning(f"Profieltype {code}: ook de link uit de pagina gaf geen PNG "
                            f"({len(found)} bytes)")
    raise HttpError(url, None, f"antwoord voor profieltype {code} is geen PNG")


def codes_without_a_drawing(result: StudyResult, targets: Dict[str, str], log=None) -> Set[str]:
    """The profile types the WFS gave no usable drawing URL for.

    The same fact as a portal page that says not found, reached one step earlier: there is nothing
    to fetch, so DOV publishes no drawing for this type. Read as "not fetched" it made the report
    contradict itself - a legend line sending the reader to a sources chapter that never mentioned
    it, because nothing was ever fetched and so nothing was ever recorded. The units table of the
    map sheet is cut from that same drawing, so a sheet whose only type lands here has no units
    page either; the line in the sources chapter is what explains both.
    """
    known = set(targets.values())
    missing = {str(row.get(QUARTAIR_CODE)) for fact in result.map_facts
               if fact.map_id == QUARTAIR_ID for row in fact.rows
               if row.get(QUARTAIR_CODE) and str(row.get(QUARTAIR_CODE)) not in known}
    if missing and log is not None:
        log.warning(f"Profieltype zonder bruikbare tekening-URL: {', '.join(sorted(missing))}")
    return missing


def prepare_zone_legend_images(result: StudyResult, out_dir, client: HttpClient, log=None,
                               should_cancel: Optional[Callable[[], bool]] = None
                               ) -> Tuple[Dict[str, Path], Set[str]]:
    """The DOV drawings behind the quartair zone legend, by the key `report_content` looks them up
    with: `profieltype:<code>` for the header strip of one type, `kaartblad:<nn>` for the units
    table of a whole map sheet.

    That drawing IS the legend of the quartair map - its GetLegendGraphic is a 20 x 20 stamp
    without a class name - so the shell fetches it here and hands it to `build_report`. The core
    fetches nothing itself.

    One request per distinct profile type; the units table underneath is identical for every type
    of the same sheet, so it is kept once. What does not come back has no entry, and the report
    then leaves that page out rather than promising a drawing that is not there. The URLs end in
    "_png" but are download links that can answer an error page with HTTP 200, so the bytes are
    checked before they are saved as an image.
    """
    targets = zone_legend_targets(result)
    drawings: Dict[str, Path] = {}
    # De codes waarvoor er niets te halen valt: het portaal zegt dat er niets bestaat, of de WFS
    # gaf geen enkele link. Apart van "niet opgehaald": de bron publiceert hier niets, en dat is
    # een feit en geen storing.
    unpublished: Set[str] = codes_without_a_drawing(result, targets, log)
    out_dir = Path(out_dir)

    def fetch(item: Tuple[str, str]) -> None:
        url, code = item
        try:
            data = _drawing_bytes(client, url, code, log)
        except NoDrawingPublished:
            unpublished.add(code)
            return
        path = out_dir / LEGEND_DIR / f"{ZONE_LEGEND_PREFIX}{code}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        drawings[code] = path

    parallel.load_each(list(targets.items()), fetch, "profieltypelegenda", LEGEND_WORKERS, log,
                       should_cancel)
    # The threads only fetch; the cutting and the one-per-sheet choice happen here, in the order
    # the WFS rows first mentioned each profile type, so two runs of the same study keep the same
    # sheet drawing.
    images: Dict[str, Path] = {}
    for code in targets.values():
        drawing = drawings.get(code)
        if drawing is None:
            continue
        header = crop_profile_header(drawing, log)
        if header is None:
            continue
        images[profile_image_key(code)] = header
        sheet = quartair_sheet(code)
        key = sheet_image_key(sheet)
        if key not in images:
            units = crop_sheet_units(drawing, sheet, log)
            if units is not None:
                images[key] = units
    if log and targets:
        log.info(f"Profieltypetekeningen opgehaald: {len(drawings)}/{len(targets)}; "
                 f"{len(images)} bladen in het rapport")
    return images, unpublished


# --- the map images -----------------------------------------------------------------------------

@dataclass(frozen=True)
class MapRequest:
    """One map image to fetch: which map, over which box, at which pixel size."""
    key: str
    map_id: str
    extent: QgsRectangle
    width: int
    height: int


def wms_map_url(entry: MapEntry, extent: QgsRectangle, width: int, height: int) -> str:
    """A GetMap for one box at one pixel size.

    WMS 1.1.1 on purpose: 1.3.0 orders the BBOX by the axis order of the CRS, and getting that
    wrong for EPSG:31370 yields a picture of somewhere else - which would read as an empty map.
    1.1.1 is always minx,miny,maxx,maxy, and every service in the catalogue answers it (checked
    live 2026-09-16 on geopunt, DOV, waterinfo and NGI).
    """
    params = {"SERVICE": "WMS", "VERSION": "1.1.1", "REQUEST": "GetMap", "LAYERS": entry.wms_layer,
              "STYLES": entry.wms_style, "SRS": CRS_AUTHID, "FORMAT": entry.image_format,
              "TRANSPARENT": "TRUE", "WIDTH": width, "HEIGHT": height,
              "BBOX": f"{extent.xMinimum():.0f},{extent.yMinimum():.0f},"
                      f"{extent.xMaximum():.0f},{extent.yMaximum():.0f}"}
    if entry.sld_body:
        # Our own lettering for a map whose published style is unreadable at report size. The
        # service still draws the geometry; only the labels are ours. It travels in the URL, so
        # this one map has a GetMap of a few kilobytes - the sources table prints it shortened.
        params["SLD_BODY"] = entry.sld_body
    return build_url(entry.wms_url, params)


def _image_name(key: str) -> str:
    """The file-name part that tells two framings of one map apart, stable across runs.

    `hash()` on a str is salted per process (PYTHONHASHSEED), so a headless run reusing the same
    `--out` left a new set of orphans behind every time and two framings could collide on one
    name. A digest of the key does neither.
    """
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:8]


def _image_pixels() -> Tuple[int, int]:
    """The pixel size a map item is printed at, capped at what a service hands out in one go."""
    width = int(round(MAP_W / 25.4 * MAP_IMAGE_DPI))
    height = int(round(MAP_H / 25.4 * MAP_IMAGE_DPI))
    largest = max(width, height)
    if largest > MAP_IMAGE_MAX_PX:
        width = int(width * MAP_IMAGE_MAX_PX / largest)
        height = int(height * MAP_IMAGE_MAX_PX / largest)
    return width, height


def plan_map_images(report: Report, zone_ring: Sequence,
                    boxes: Dict[str, Sequence]) -> List[MapRequest]:
    """One request per distinct (map, box) in the report, in the order the pages need them.

    The box is computed here exactly as the page will compute it, overlays included - a page that
    widens for the search radius shows a wider picture and must ask for that picture. `boxes` is
    what `overlay_boxes` gives for the study; no layer is needed, so this runs on a worker thread.
    """
    requests: List[MapRequest] = []
    seen = set()
    for chapter in report.chapters:
        for page in chapter.pages:
            if not isinstance(page, MapPage):
                continue
            extent, key = page_image(page, zone_ring, boxes)
            if key in seen:
                continue
            seen.add(key)
            width, height = _image_pixels()
            requests.append(MapRequest(key, page.map_id, extent, width, height))
    return requests


def _write_world_file(path: Path, request: MapRequest) -> None:
    """The six lines that put a PNG on the map: pixel size, rotation, and the centre of the
    top-left pixel (not its corner - that half pixel is the classic world-file mistake)."""
    x_size = request.extent.width() / request.width
    y_size = request.extent.height() / request.height
    path.write_text("\n".join((f"{x_size:.10f}", "0.0", "0.0", f"{-y_size:.10f}",
                                f"{request.extent.xMinimum() + x_size / 2:.4f}",
                                f"{request.extent.yMaximum() - y_size / 2:.4f}")) + "\n",
                    encoding="utf-8")


def _backdrop_for(request: MapRequest, client: HttpClient, log=None) -> Tuple[Optional[QImage], str]:
    """The base map under one theme: (image, why not). A backdrop that does not come back costs
    the theme its background, never its page."""
    base = catalogue.by_id(BASE_MAP_ID)
    url = wms_map_url(base, request.extent, request.width, request.height)
    try:
        image = load_tile(client.get(url, timeout=MAP_IMAGE_TIMEOUT_S, retries=MAP_IMAGE_RETRIES))
    except HttpError as exc:
        image, reason = None, str(exc)
    else:
        reason = "" if image is not None else "antwoord van de basiskaart is geen afbeelding"
    if image is None and log:
        log.warning(f"Ondergrond voor {request.map_id} niet opgehaald: {reason}")
    return image, reason


def prepare_map_images(requests: Sequence[MapRequest], out_dir, client: HttpClient, log=None,
                       should_cancel: Optional[Callable[[], bool]] = None
                       ) -> Tuple[Dict[str, Path], Set[str], Dict[str, str]]:
    """({key -> PNG}, keys whose service drew nothing here), fetched in parallel.

    This is the phase that used to be spread over ninety sheets of rendering: the WMS provider
    fetches its tiles while a page draws, one page after another, and the whole report waits on
    the network. Here every page's background is one GetMap, they go out together, and the layout
    then draws local files.

    Emptiness comes for free with the picture, so the separate coverage probe is gone, and it is
    asked of EVERY map - the ones that carry facts included. What an empty tile COSTS is decided
    later, where the legend that would stand under the sheet is known
    (`pipeline._pages_without_an_image`): the watertoets answers Gent with a fully transparent tile
    because no flood zone lies there - data, not a hole in the mosaic - and the units beside it
    keep the sheet.

    Emptiness is reported per REQUEST, not per map: one map carries several framings (the GRB base
    map three), and a mosaic that has no sheet for the wide frame may well cover the narrow one.
    Keyed per map, one empty tile would print "geen dekking" on every other sheet of that map.

    The third answer is the backdrops: map id -> "" when the base map went under that theme, or
    the reason it did not. Only for `MapEntry.backdrop` maps, and only ever as an extra request -
    a theme whose backdrop failed is still drawn, on white paper, and says so in the sources.
    """
    out_dir = Path(out_dir)
    images: Dict[str, Path] = {}
    empty: Set[str] = set()
    backdrops: Dict[str, str] = {}

    def fetch(request: MapRequest) -> None:
        entry = catalogue.by_id(request.map_id)
        url = wms_map_url(entry, request.extent, request.width, request.height)
        data = client.get(url, timeout=MAP_IMAGE_TIMEOUT_S, retries=MAP_IMAGE_RETRIES)
        image = load_tile(data)
        if image is None:
            raise HttpError(url, None, f"antwoord voor {request.map_id} is geen afbeelding "
                                       f"({len(data)} bytes)")
        # Asked of the THEME, before anything is painted under it: a backdrop would answer the
        # coverage question with the base map's own ink. Asked of EVERY map, not only of the ones
        # without facts - a themed map that draws nothing here is the sheet that showed a base map,
        # an empty legend and a guide to a table that was not there. What such a tile costs is
        # decided where the legend is known (`pipeline._pages_without_an_image`), not here.
        blank = is_empty(image)
        path = out_dir / DATA_DIR / MAP_IMAGE_DIR / f"{request.map_id}_{_image_name(request.key)}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        if entry.backdrop:
            under, reason = _backdrop_for(request, client, log)
            # Keyed per MAP while eight threads write it, so two framings of one map race for the
            # same slot. Both framings ask the same base map, so the two answers are the same
            # sentence and the winner does not matter; CPython's dict assignment is atomic, so
            # nothing is lost either. Keep the LOSING one only when it explains a failure that the
            # winner does not, so a reason never silently becomes "fine".
            if reason or request.map_id not in backdrops:
                backdrops[request.map_id] = reason
            if under is not None:
                data = None
                if not over_backdrop(image, under, entry.opacity).save(str(path)):
                    raise HttpError(url, None, f"beeld van {request.map_id} niet weggeschreven")
        if data is not None:
            path.write_bytes(data)
        _write_world_file(path.with_suffix(".pgw"), request)
        images[request.key] = path
        if blank:
            empty.add(request.key)

    parallel.load_each(list(requests), fetch, "kaartbeeld", MAP_IMAGE_WORKERS, log, should_cancel)
    if log:
        blank = sorted({request.map_id for request in requests if request.key in empty})
        log.info(f"Kaartbeelden opgehaald: {len(images)}/{len(requests)}"
                 + (f"; geen kaartbeeld op deze locatie voor: {', '.join(blank)}" if blank else ""))
        missing = [request.map_id for request in requests if request.key not in images]
        if missing:
            log.warning(f"Geen kaartbeeld voor: {', '.join(sorted(set(missing)))}")
        under = sorted(map_id for map_id, reason in backdrops.items() if not reason)
        if under:
            log.info(f"Basiskaart als ondergrond onder: {', '.join(under)}")
    return images, empty, backdrops
