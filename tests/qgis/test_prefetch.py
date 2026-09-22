"""De netwerkhelft van de schil: legenda's, profieltypetekeningen en kaartbeelden.

Wat hier gebeurt draait in de plugin op de werkthread, dus geen enkele test hier bouwt een layout
of raakt een QgsProject aan. Offline waar het kan - de "dienst" is een client die vaste bytes
teruggeeft - met een enkele live-test die bewijst dat de GetLegendGraphic-URL echt klopt.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tests.qgis.conftest import (
    drawn_png,
    pixels,
    profile_drawing,
    report_of,
    solid_png,
    tile,
)
from tests.qgis.conftest import write_png as _png

MAP_ID = "grb"  # een echte catalogusentry: de layout leest er titel, attributie en licentie uit


def _quartair_result(gent_zone, codes):
    from desktopstudie.core.model import StudyResult
    from tests import quartair

    result = StudyResult(zone=gent_zone, created_at="2026-09-15T10:00:00")
    result.map_facts = [quartair.map_fact(codes)]
    return result


class _TileClient:
    """Een client die per laagnaam een vaste tegel teruggeeft en de opgevraagde lagen onthoudt."""

    def __init__(self, tiles, failing=()):
        self.tiles, self.failing, self.asked = tiles, set(failing), []

    def get(self, url, params=None, timeout=None, retries=None, cache_mode=None):
        from desktopstudie.core.services.http import HttpError

        layer = url.split("LAYERS=")[1].split("&")[0]
        self.asked.append(layer)
        if layer in self.failing:
            raise HttpError(url, 500, "dienst plat")
        return self.tiles[layer]


def _one_request(map_id, gent_zone):
    from desktopstudie.core import catalogue
    from desktopstudie.qgis import layout, prefetch

    entry = catalogue.by_id(map_id)
    extent = layout.map_extent(gent_zone.ring, entry.scale, 3.0)
    return prefetch.MapRequest(layout.map_image_key(map_id, extent), map_id, extent, 40, 40)


def test_the_legend_url_asks_for_the_style_and_the_column_layout():
    """Een legenda hoort bij een laag en bij een stijl: gxg zonder stijl tekent een andere legenda
    dan de kaart. LEGEND_OPTIONS houdt de klassen in kolommen in plaats van in een strook."""
    from desktopstudie.core import catalogue
    from desktopstudie.qgis import prefetch

    entry = catalogue.by_id("gxg_ghg")
    url = prefetch.wms_legend_url(entry, entry.legend_options)

    assert "REQUEST=GetLegendGraphic" in url and "VERSION=1.3.0" in url
    # the workspace service, on which the layer goes by its bare name; the style keeps its prefix
    assert url.startswith("https://www.dov.vlaanderen.be/geoserver/gxg/wms?")
    assert "LAYER=ghg_mmv_main&" in url
    assert "STYLE=gxg%3Agxg" in url or "STYLE=gxg:gxg" in url
    assert "LEGEND_OPTIONS=" in url and "columns" in url
    assert "LEGEND_OPTIONS" not in prefetch.wms_legend_url(entry, "")


def test_a_legend_that_cannot_be_fetched_is_reported_not_swallowed(qgs_app, tmp_path):
    """Een bron die faalt, faalt luid: geen pad terug en een WARNING."""
    from dataclasses import replace

    from desktopstudie.core import catalogue
    from desktopstudie.core.logging_util import Log
    from desktopstudie.core.services.http import HttpClient
    from desktopstudie.qgis import prefetch

    entry = replace(catalogue.by_id("gxg_ghg"), wms_url="http://127.0.0.1:9/wms")
    lines = []
    client = HttpClient(cache_dir=None, timeout=1.0, retries=0, sleep=lambda _s: None)

    assert prefetch.fetch_legend(entry, tmp_path, client, Log("layout", lines.append, scope="qgis")) is None
    assert any("WARNING" in line for line in lines), lines


def test_prepare_legends_skips_maps_without_a_legend(qgs_app, tmp_path):
    """Kaarten met legend=False worden niet opgehaald - de bodemkaart alleen al zou een strook van
    duizenden pixels binnenhalen die nergens op past."""
    from desktopstudie.core import catalogue
    from desktopstudie.core.services.http import HttpClient
    from desktopstudie.qgis import prefetch

    asked = []
    blob = _png(tmp_path / "bron.png").read_bytes()

    class _Client(HttpClient):
        def get(self, url, params=None, timeout=None, retries=None, cache_mode=None):
            asked.append((url, timeout, retries))
            return blob

    entries = [catalogue.by_id("bodemkaart"), catalogue.by_id("tertiair")]
    images, missing = prefetch.prepare_legends(entries, tmp_path, _Client(cache_dir=None))

    assert list(images) == ["tertiair"]
    assert missing == []
    assert len(asked) == 1 and "tertiair_50k" in asked[0][0]
    # Een legenda is één plaatje uit een reeks: een korte adem, net als een fiche. Drie keer een
    # volle minuut wachten op een dienst die plat ligt, kost het rapport zijn legendapagina's.
    assert asked[0][1:] == (prefetch.LEGEND_TIMEOUT_S, prefetch.LEGEND_RETRIES)


@pytest.mark.live
def test_live_the_gxg_legend_is_a_real_png(qgs_app, tmp_path):
    from desktopstudie.core import catalogue
    from desktopstudie.core.services.http import HttpClient
    from desktopstudie.qgis import prefetch

    path = prefetch.fetch_legend(catalogue.by_id("gxg_ghg"), tmp_path, HttpClient(cache_dir=None))

    assert path is not None and path.exists()
    assert path.stat().st_size > 1024
    assert path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_the_profile_type_drawings_are_fetched_once_per_type(qgs_app, tmp_path, gent_zone):
    """De echte legenda van de Quartairkaart is een tekening per profieltype. Twee kaartvlakken van
    hetzelfde type vragen om een tekening, en een tekening die de dienst niet levert, levert geen
    bestand op - een lege figuurpagina belooft de lezer een legenda die er niet is."""
    from desktopstudie.core.logging_util import Log
    from desktopstudie.core.report_content import profile_image_key, sheet_image_key
    from desktopstudie.core.services.http import HttpClient, HttpError
    from desktopstudie.qgis import prefetch

    blob = profile_drawing(tmp_path / "bron.png").read_bytes()
    asked = []

    class _Client(HttpClient):
        def get(self, url, params=None, timeout=None, retries=None, cache_mode=None):
            asked.append((url, timeout, retries))
            if url.endswith("22098_png"):
                raise HttpError(url, 500, "dienst plat")
            return blob

    lines = []
    result = _quartair_result(gent_zone, ["22026", "22010", "22026", "22098"])

    images, _unpublished = prefetch.prepare_zone_legend_images(result, tmp_path, _Client(cache_dir=None),
                                               Log("layout", lines.append, scope="qgis"))

    # Een kopstrook per profieltype, en de eenhedentabel een keer voor het hele kaartblad.
    assert set(images) == {profile_image_key("22026"), profile_image_key("22010"),
                           sheet_image_key("22")}
    assert images[profile_image_key("22026")].name == "quartair_22026_kop.png"
    assert images[sheet_image_key("22")].name == "quartair_kaartblad_22.png"
    # De eenhedentabel van het blad houdt alles behalve de kop van het profieltype waarmee ze
    # binnenkwam; die kop staat al op de legendapagina.
    assert images[sheet_image_key("22")].read_bytes() != blob
    assert len(asked) == 3, "hetzelfde profieltype wordt niet twee keer opgehaald"
    # Ruimer dan een GetLegendGraphic-stempel, want dit is een bestand uit een documentportaal:
    # 168 kB haalt vijftien seconden op een trage dag niet. Wel begrensd - een dienst die plat
    # ligt mag het rapport geen drie volle minuten kosten.
    assert asked[0][1:] == (prefetch.DRAWING_TIMEOUT_S, prefetch.LEGEND_RETRIES)
    assert prefetch.DRAWING_TIMEOUT_S > prefetch.LEGEND_TIMEOUT_S
    assert any("WARNING" in line for line in lines), lines


def test_the_header_strip_is_cut_above_the_units_table(qgs_app, tmp_path, gent_zone):
    """De kopstrook is het deel dat per profieltype verschilt; de eenhedentabel eronder is voor elk
    type van hetzelfde kaartblad dezelfde. De snede valt in de witte band ertussen, dus de strook
    is korter dan de tekening en breder dan hoog."""
    from qgis.PyQt.QtGui import QImage

    from desktopstudie.core.report_content import profile_image_key
    from desktopstudie.core.services.http import HttpClient
    from desktopstudie.qgis import prefetch

    blob = profile_drawing(tmp_path / "bron.png").read_bytes()

    class _Client(HttpClient):
        def get(self, url, params=None, timeout=None, retries=None, cache_mode=None):
            return blob

    images, _unpublished = prefetch.prepare_zone_legend_images(_quartair_result(gent_zone, ["22026"]), tmp_path,
                                               _Client(cache_dir=None))

    header = QImage(str(images[profile_image_key("22026")]))
    whole = QImage(str(tmp_path / "bron.png"))
    assert header.width() == whole.width()
    assert header.height() < whole.height() / 2, "de eenhedentabel hoort er niet meer op te staan"
    assert header.height() > 60, "het kleurvlak en de omschrijving horen er wel op te staan"
    assert header.width() > header.height()


def test_the_sheet_drawing_loses_the_profile_header(qgs_app, tmp_path, gent_zone):
    """De eenhedentabel geldt voor elk profieltype van het blad. Stond de kop van profieltype 22010
    er nog boven, dan leest ze als de tabel van dat ene type - dus die kop gaat eraf, en de bronregel
    onder de tabel blijft staan."""
    from qgis.PyQt.QtGui import QImage

    from desktopstudie.core.report_content import profile_image_key, sheet_image_key
    from desktopstudie.core.services.http import HttpClient
    from desktopstudie.qgis import prefetch

    blob = profile_drawing(tmp_path / "bron.png").read_bytes()

    class _Client(HttpClient):
        def get(self, url, params=None, timeout=None, retries=None, cache_mode=None):
            return blob

    images, _unpublished = prefetch.prepare_zone_legend_images(_quartair_result(gent_zone, ["22026"]), tmp_path,
                                               _Client(cache_dir=None))

    whole = QImage(str(tmp_path / "bron.png"))
    header = QImage(str(images[profile_image_key("22026")]))
    units = QImage(str(images[sheet_image_key("22")]))
    assert units.width() == whole.width()
    assert units.height() == whole.height() - header.height(), "precies de kop eraf"
    assert units.height() > whole.height() / 2, "de tabel zelf staat er nog helemaal op"


def test_an_answer_that_is_no_image_is_asked_again_past_the_cache(qgs_app, tmp_path, gent_zone):
    """De legenda-URL's van DOV zijn downloadlinks die soms met HTTP 200 de webpagina van de dienst
    teruggeven in plaats van het bestand (live gezien op 2026-09-16). Die pagina als PNG
    wegschrijven levert een figuurpagina met een leeg kader, en in de schijfcache zou ze elke
    volgende run bederven - dus wordt er nog een keer gevraagd, langs de cache heen."""
    from desktopstudie.core.report_content import profile_image_key
    from desktopstudie.core.services.http import HttpClient
    from desktopstudie.qgis import prefetch

    blob = profile_drawing(tmp_path / "bron.png").read_bytes()
    asked = []

    class _Client(HttpClient):
        def get(self, url, params=None, timeout=None, retries=None, cache_mode=None):
            asked.append(cache_mode)
            return b"<html><body>DSpace</body></html>" if len(asked) == 1 else blob

    images, _unpublished = prefetch.prepare_zone_legend_images(_quartair_result(gent_zone, ["22026"]), tmp_path,
                                               _Client(cache_dir=None))

    assert profile_image_key("22026") in images
    assert asked == [None, "refresh"], "de herkansing hoort de cache over te slaan"


def test_an_answer_that_is_never_an_image_is_not_saved_as_one(qgs_app, tmp_path, gent_zone):
    """Blijft de dienst haar webpagina geven, dan komt er geen bestand en geen figuurpagina - een
    mislukte bron, geen leeg kader."""
    from desktopstudie.core.services.http import HttpClient
    from desktopstudie.qgis import prefetch

    class _Client(HttpClient):
        def get(self, url, params=None, timeout=None, retries=None, cache_mode=None):
            return b"<html><body>Service unavailable</body></html>"

    images, _unpublished = prefetch.prepare_zone_legend_images(_quartair_result(gent_zone, ["22026"]), tmp_path,
                                               _Client(cache_dir=None))

    assert images == {}
    assert not (tmp_path / "legendas" / "quartair_22026.png").exists()


def test_a_study_without_quartair_rows_asks_for_nothing(qgs_app, tmp_path, gent_zone):
    from desktopstudie.core.model import StudyResult
    from desktopstudie.core.services.http import HttpClient
    from desktopstudie.qgis import prefetch

    class _Client(HttpClient):
        def get(self, url, params=None, timeout=None, retries=None, cache_mode=None):
            raise AssertionError(f"niets op te halen, en toch gevraagd: {url}")

    assert prefetch.prepare_zone_legend_images(
        StudyResult(zone=gent_zone, created_at="t"), tmp_path, _Client(cache_dir=None)) == ({}, set())


def test_a_profile_type_the_wfs_gives_no_drawing_link_for_counts_as_unpublished(gent_zone, tmp_path):
    """Het rapport sprak zichzelf tegen: onder de kaart stond "tekening niet opgehaald - zie
    hoofdstuk Bronnen" terwijl de Feiten "Bronnen niet beschikbaar: 0" zeiden en hoofdstuk Bronnen
    er geen regel over had. De WFS gaf voor dat profieltype namelijk geen enkele link, dus werd er
    ook nooit iets opgehaald en viel er niets te melden. Geen link is hetzelfde feit als een
    niet-gevonden-pagina: DOV publiceert hier geen tekening."""
    from desktopstudie.core.model import MapFact, StudyResult
    from desktopstudie.core.services.http import HttpClient
    from desktopstudie.qgis import prefetch
    from tests import quartair

    class _Client(HttpClient):
        def get(self, url, params=None, timeout=None, retries=None, cache_mode=None):
            raise AssertionError(f"er is geen link, en toch gevraagd: {url}")

    result = StudyResult(zone=gent_zone, created_at="t")
    result.map_facts = [MapFact("quartair", quartair.TITLE,
                                [{"profieltype": "13064", "legende": None}])]

    images, unpublished = prefetch.prepare_zone_legend_images(result, tmp_path,
                                                            _Client(cache_dir=None))

    assert images == {}
    assert unpublished == {"13064"}


def test_a_row_without_a_drawing_url_is_named_in_the_log(qgs_app, tmp_path, gent_zone):
    """Een profieltype zonder bruikbare legenda-URL levert een regel zonder tekening op. Zonder
    logregel is dat niet te onderscheiden van een download die mislukte - en wat NIET gevonden is,
    hoort in het log."""
    from desktopstudie.core.logging_util import Log
    from desktopstudie.core.model import MapFact, StudyResult
    from desktopstudie.core.services.http import HttpClient
    from desktopstudie.qgis import prefetch
    from tests import quartair

    blob = profile_drawing(tmp_path / "bron.png").read_bytes()

    class _Client(HttpClient):
        def get(self, url, params=None, timeout=None, retries=None, cache_mode=None):
            return blob

    result = StudyResult(zone=gent_zone, created_at="t")
    result.map_facts = [MapFact("quartair", "Quartair", [
        quartair.rows(["22026"])[0], {"profieltype": "22099", "legende": None}])]
    lines = []

    prefetch.prepare_zone_legend_images(result, tmp_path, _Client(cache_dir=None),
                                      Log("layout", lines.append, scope="qgis"))

    assert any("22099" in line and "WARNING" in line for line in lines), lines
    assert not any("22026" in line and "WARNING" in line for line in lines), lines


def test_two_pages_of_the_same_map_at_the_same_extent_share_one_image(project, gent_zone, tmp_path):
    """De GRB-basiskaart staat op vier bladen. Waar de uitsnede dezelfde is, hoeft ze maar een keer
    opgehaald te worden; waar ze verschilt (hoofdstuk 5 rekt open voor de zoekstraal) niet."""
    from desktopstudie.core.report_content import MapPage
    from desktopstudie.qgis import prefetch

    pages = [MapPage("grb", "Ligging", scale=2500), MapPage("grb", "Nog eens", scale=2500),
             MapPage("grb", "Overzicht", scale=5000, extent_factor=1.0)]

    requests = prefetch.plan_map_images(report_of(pages), gent_zone.ring, {})

    assert len(requests) == 2, [request.key for request in requests]
    assert len({request.key for request in requests}) == 2


def test_a_fetched_map_image_lands_next_to_its_world_file(qgs_app, gent_zone, tmp_path):
    """Een PNG zonder wereldbestand ligt nergens: de layout moet hem op de meter kunnen plaatsen."""
    from desktopstudie.core.report_content import MapPage
    from desktopstudie.core.services.http import HttpClient
    from desktopstudie.qgis import prefetch

    blob = drawn_png(tmp_path / "tegel.png", 120, 130).read_bytes()
    asked = []

    class _Client(HttpClient):
        def get(self, url, params=None, timeout=None, retries=None, cache_mode=None):
            asked.append((url, timeout, retries))
            return blob

    requests = prefetch.plan_map_images(report_of([MapPage("grb", "Ligging", scale=2500)]),
                                      gent_zone.ring, {})

    images, empty, _backdrops = prefetch.prepare_map_images(requests, tmp_path,
                                                          _Client(cache_dir=None))

    path = images[requests[0].key]
    assert path.parent.name == prefetch.MAP_IMAGE_DIR and path.suffix == ".png"
    world = path.with_suffix(".pgw")
    assert world.exists()
    lines = world.read_text(encoding="utf-8").splitlines()
    extent = requests[0].extent
    assert float(lines[0]) == pytest.approx(extent.width() / requests[0].width, rel=1e-6)
    assert float(lines[3]) == pytest.approx(-extent.height() / requests[0].height, rel=1e-6)
    assert float(lines[4]) == pytest.approx(extent.xMinimum() + float(lines[0]) / 2, rel=1e-6)
    assert empty == set()
    assert "REQUEST=GetMap" in asked[0][0] and "VERSION=1.1.1" in asked[0][0]
    assert asked[0][1:] == (prefetch.MAP_IMAGE_TIMEOUT_S, prefetch.MAP_IMAGE_RETRIES)


def test_an_empty_map_image_is_the_coverage_answer_too(qgs_app, gent_zone, tmp_path):
    """De dekkingsproef was een extra GetMap per kaart. Nu het beeld er toch al is, valt het
    antwoord eruit: een volledig lege tegel betekent geen kaartbeeld op deze locatie, voor ELKE
    kaart. Wat zo'n tegel kost wordt beslist waar de legenda bekend is - met eenheden eronder
    blijft het blad, zonder eenheden vervalt het - en niet hier."""
    from desktopstudie.core.report_content import MapPage
    from desktopstudie.core.services.http import HttpClient
    from desktopstudie.qgis import prefetch

    leeg = solid_png(tmp_path / "leeg.png", 64, 64).read_bytes()

    class _Client(HttpClient):
        def get(self, url, params=None, timeout=None, retries=None, cache_mode=None):
            return leeg

    pages = [MapPage("popp", "Popp", scale=5000), MapPage("watertoets_pluviaal", "Watertoets",
                                                          scale=10000)]
    requests = prefetch.plan_map_images(report_of(pages), gent_zone.ring, {})

    _images, empty, _backdrops = prefetch.prepare_map_images(requests, tmp_path,
                                                           _Client(cache_dir=None))

    assert empty == {request.key for request in requests}, "elke lege tegel, per kader gemeten"


def test_a_map_image_that_fails_leaves_no_file_and_no_coverage_claim(qgs_app, gent_zone, tmp_path):
    from desktopstudie.core.logging_util import Log
    from desktopstudie.core.report_content import MapPage
    from desktopstudie.core.services.http import HttpClient, HttpError
    from desktopstudie.qgis import prefetch

    class _Down(HttpClient):
        def get(self, url, params=None, timeout=None, retries=None, cache_mode=None):
            raise HttpError(url, 500, "dienst plat")

    requests = prefetch.plan_map_images(report_of([MapPage("popp", "Popp", scale=5000)]),
                                      gent_zone.ring, {})
    lines = []

    images, empty, _backdrops = prefetch.prepare_map_images(requests, tmp_path, _Down(cache_dir=None),
                                              Log("layout", lines.append, scope="qgis"))

    assert images == {} and empty == set(), "een mislukte ophaling zegt niets over dekking"
    assert any("WARNING" in line for line in lines), lines


def test_a_portal_page_is_followed_to_the_file_and_never_kept(qgs_app, tmp_path, gent_zone):
    """Stuurt het portaal zijn eigen webpagina in plaats van de tekening, dan wijst die pagina zelf
    naar het bestand: die link wordt gevolgd. En de pagina blijft niet in de cache staan, want dan
    kwam ze er bij elke volgende run zonder netwerk weer uit."""
    from desktopstudie.core.report_content import profile_image_key
    from desktopstudie.core.services.http import HttpClient
    from desktopstudie.qgis import prefetch

    blob = profile_drawing(tmp_path / "bron.png").read_bytes()
    link = ("https://datasets-services.omgeving.vlaanderen.be/server/api/core/bitstreams/"
            "0082d459-f86d-4a5b-9508-bbb98ae38e88/content")
    page = ('<html>' + link + '"_name":"DOV_Quartair_50000_22026.png"</html>').encode()
    asked, forgotten = [], []

    class _Client(HttpClient):
        def get(self, url, params=None, timeout=None, retries=None, cache_mode=None):
            asked.append(url)
            return blob if url == link else page

        def forget(self, url):
            forgotten.append(url)
            return True

    images, _unpublished = prefetch.prepare_zone_legend_images(_quartair_result(gent_zone, ["22026"]), tmp_path,
                                               _Client(cache_dir=None))

    assert profile_image_key("22026") in images, (
        "de tekening hoort er via de link uit de pagina te zijn")
    assert link in asked, "de link uit de pagina is niet gevolgd"
    assert any(url.endswith("_png") for url in forgotten), (
        "de webpagina hoort uit de cache gegooid te worden")


def test_a_sparse_theme_is_painted_over_the_base_map(qgs_app, gent_zone, tmp_path):
    """Een thema dat bijna niets tekent, levert op wit papier een leeg blad. Het beeld dat de
    pagina afdrukt draagt daarom de basiskaart eronder: straten en gebouwen onder het thema."""
    from desktopstudie.core import catalogue
    from desktopstudie.qgis import prefetch

    theme_id = "grondverschuiving_gekarteerd"
    tiles = {catalogue.by_id(theme_id).wms_layer: tile((255, 0, 0), alpha=0),
             catalogue.by_id(catalogue.BASE_MAP_ID).wms_layer: tile((0, 0, 255))}
    request = _one_request(theme_id, gent_zone)

    images, _empty, backdrops = prefetch.prepare_map_images([request], tmp_path,
                                                          _TileClient(tiles))

    assert backdrops == {theme_id: ""}, "de ondergrond hoort als eigen bron gemeld te worden"
    drawn = pixels(images[request.key]).pixelColor(20, 20)
    assert (drawn.red(), drawn.green(), drawn.blue()) == (0, 0, 255), (
        "waar het thema niets tekent, hoort de basiskaart te staan")


def test_a_map_that_fills_the_sheet_itself_asks_for_no_base_map(qgs_app, gent_zone, tmp_path):
    """De bodemkaart bedekt de hele uitsnede; een ondergrond eronder is werk dat niemand ziet."""
    from desktopstudie.core import catalogue
    from desktopstudie.qgis import prefetch

    tiles = {catalogue.by_id("bodemkaart").wms_layer: tile((0, 200, 0))}
    request = _one_request("bodemkaart", gent_zone)
    client = _TileClient(tiles)

    images, _empty, backdrops = prefetch.prepare_map_images([request], tmp_path, client)

    assert backdrops == {}
    assert client.asked == [catalogue.by_id("bodemkaart").wms_layer], client.asked
    assert images


def test_a_backdrop_that_fails_costs_the_theme_its_background_not_its_page(qgs_app, gent_zone,
                                                                           tmp_path):
    """Valt de basiskaart weg, dan wordt het thema alleen getekend - het blad blijft - en de
    bronnenlijst zegt dat de ondergrond ontbrak."""
    from desktopstudie.core import catalogue
    from desktopstudie.core.logging_util import Log
    from desktopstudie.qgis import prefetch

    theme_id = "watertoets_pluviaal"
    base = catalogue.by_id(catalogue.BASE_MAP_ID).wms_layer
    tiles = {catalogue.by_id(theme_id).wms_layer: tile((255, 0, 0)), base: b""}
    request = _one_request(theme_id, gent_zone)
    lines = []

    images, _empty, backdrops = prefetch.prepare_map_images(
        [request], tmp_path, _TileClient(tiles, failing={base}),
        Log("kaarten", lines.append))

    assert request.key in images, "het thema houdt zijn blad"
    assert backdrops[theme_id], "de reden hoort bewaard te blijven"
    assert any("ondergrond" in line.lower() for line in lines), lines


def test_the_theme_keeps_its_own_colours_over_the_backdrop(qgs_app, gent_zone, tmp_path):
    """Waar het thema wel tekent, blijft het thema zichtbaar - de basiskaart schemert eronder door
    met de doorzichtigheid die de catalogus voor die kaart kiest."""
    from desktopstudie.core import catalogue
    from desktopstudie.qgis import prefetch

    theme_id = "grondverschuiving_gekarteerd"
    tiles = {catalogue.by_id(theme_id).wms_layer: tile((255, 0, 0)),
             catalogue.by_id(catalogue.BASE_MAP_ID).wms_layer: tile((0, 0, 255))}
    request = _one_request(theme_id, gent_zone)

    images, _empty, _backdrops = prefetch.prepare_map_images([request], tmp_path, _TileClient(tiles))

    drawn = pixels(images[request.key]).pixelColor(20, 20)
    assert drawn.red() > drawn.blue(), "het thema hoort bovenop te liggen"
    assert drawn.blue() > 0, "en de basiskaart hoort er doorheen te schemeren"


def test_a_map_that_brings_its_own_lettering_sends_it_along(qgs_app):
    """De isopachenkaart vraagt haar eigen belettering aan met een SLD; die hoort in de GetMap
    terecht te komen, en alleen bij die kaart."""
    import urllib.parse

    from qgis.core import QgsRectangle

    from desktopstudie.core import catalogue
    from desktopstudie.qgis import prefetch

    box = QgsRectangle(100000.0, 190000.0, 104500.0, 195000.0)

    with_sld = prefetch.wms_map_url(catalogue.by_id("quartair_dikte"), box, 1063, 1181)
    without = prefetch.wms_map_url(catalogue.by_id("bodemkaart"), box, 1063, 1181)

    assert "SLD_BODY=" in with_sld and "Halo" in urllib.parse.unquote(with_sld)
    assert "SLD_BODY" not in without
    # De gateway voor de GeoServer van DOV weigert een lange URL met 502 Bad Gateway: de SLD met
    # inspringing erin gaf 3120 tekens en vijf van de vijf pogingen mislukten, dezelfde SLD zonder
    # witruimte 1905 tekens en vijf van de vijf lukten (live 2026-09-21). Ruim eronder blijven.
    assert len(with_sld) < 2500, f"GetMap van {len(with_sld)} tekens; de gateway antwoordt 502"


def test_a_profile_type_code_from_the_wfs_cannot_write_outside_the_legend_folder(qgs_app, tmp_path,
                                                                                 gent_zone):
    """De profieltypecode komt uit een WFS-rij en wordt de naam van de tekening op schijf. Een rij
    met een pad in dat veld mag niet bepalen WAAR de plugin schrijft - de tekening en de eruit
    gesneden stroken horen in legendas/ te blijven, wat de dienst ook antwoordt."""
    from desktopstudie.core.services.http import HttpClient
    from desktopstudie.qgis import prefetch

    blob = profile_drawing(tmp_path / "bron.png").read_bytes()

    class _Client(HttpClient):
        def get(self, url, params=None, timeout=None, retries=None, cache_mode=None):
            return blob

    result = _quartair_result(gent_zone, ["../../../ontsnapt"])
    out = tmp_path / "run"

    images, _unpublished = prefetch.prepare_zone_legend_images(result, out, _Client(cache_dir=None))

    assert images, "de tekening hoort gewoon opgehaald te worden, alleen veilig weggeschreven"
    legendas = (out / "legendas").resolve()
    for path in images.values():
        assert Path(path).resolve().parent == legendas, path
    assert [p for p in out.rglob("*.png")], "er is wel degelijk geschreven"
    assert all(p.resolve().parent == legendas for p in out.rglob("*.png"))
