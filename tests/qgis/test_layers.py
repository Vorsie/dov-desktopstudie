"""Lagen van een studie: WMS/WCS uit de catalogus, memory-lagen uit het model, groepen en
GeoPackage. De offline tests kijken alleen naar de URI, de geometrie en de stijl; of een service
de laag echt levert, bewijzen de live-tests onderaan (WMS- en WCS-geldigheid vergen een echte
GetCapabilities/DescribeCoverage)."""
from __future__ import annotations

import pytest

GENT = (104326.0, 192506.0)
# Een L-vormige zone van 2 x 2 km. Groot en hoekig genoeg om een cirkel om het zwaartepunt te
# ontmaskeren: die cirkel (straal = zoekstraal + de grootste halve bbox-zijde) laat de verste
# hoek van deze L buiten zich, en rekt tegelijk ver voorbij de zone waar de zone smal is.
L_RING = [(104000.0, 192000.0), (106000.0, 192000.0), (106000.0, 194000.0), (105000.0, 194000.0),
          (105000.0, 193000.0), (104000.0, 193000.0)]
L_RADIUS = 250.0
L_WEST_EDGE_X = 104000.0  # de westrand van de L, op de hoogte van de onderste balk


def _zone(ring, radius_m):
    from desktopstudie.core.model import StudyZone

    return StudyZone(ring=ring, name="L-zone", radius_m=radius_m)


def _polygon(ring):
    from qgis.core import QgsGeometry, QgsPointXY

    return QgsGeometry.fromPolygonXY([[QgsPointXY(x, y) for x, y in ring]])


def test_wms_layer_uri_from_catalogue(qgs_app):
    from desktopstudie.core import catalogue
    from desktopstudie.qgis import layers

    lyr = layers.wms_layer(catalogue.by_id("ferraris"))
    src = lyr.source()
    assert "url=https://geo.api.vlaanderen.be/HISTCART/wms" in src and "layers=ferraris" in src
    assert "crs=EPSG:31370" in src and "format=image/png" in src
    assert lyr.name() == "Ferrariskaart (1777)"


def test_wms_layer_passes_the_style_from_the_catalogue(qgs_app):
    """gxg wordt alleen correct getekend met de benoemde stijl gxg:gxg; een kaart zonder stijl
    vraagt de laagstandaard (lege styles-parameter)."""
    from desktopstudie.core import catalogue
    from desktopstudie.qgis import layers

    ghg = layers.wms_layer(catalogue.by_id("gxg_ghg")).source()
    assert "styles=gxg:gxg" in ghg
    # the workspace service, on which the layer goes by its bare name
    assert "layers=ghg_mmv_main&" in ghg and "url=https://www.dov.vlaanderen.be/geoserver/gxg/wms" in ghg
    assert "styles=&" in layers.wms_layer(catalogue.by_id("ferraris")).source()


def test_wcs_layer_uri_asks_for_geotiff(qgs_app):
    """Het WCS-formaat is de dekkingsformaatnaam GeoTIFF, niet het WMS-mimetype image/tiff:
    met image/tiff komt de laag ongeldig terug ("Cannot get test dataset")."""
    from desktopstudie.core.catalogue import DHMV_WCS_COVERAGE, DHMV_WCS_URL
    from desktopstudie.qgis import layers

    lyr = layers.wcs_layer(DHMV_WCS_URL, DHMV_WCS_COVERAGE, "DHMV II DTM 1 m")
    src = lyr.source()
    assert "url=" + DHMV_WCS_URL in src and "identifier=" + DHMV_WCS_COVERAGE in src
    assert "format=GeoTIFF" in src and "version=1.0.0" in src
    assert "crs=EPSG:31370" in src
    assert lyr.providerType() == "wcs" and lyr.name() == "DHMV II DTM 1 m"


def test_memory_layers_from_zone_and_points(qgs_app, gent_zone):
    from desktopstudie.core.model import Cpt
    from desktopstudie.qgis import layers

    zone_layer = layers.zone_layer(gent_zone)
    assert zone_layer.isValid() and zone_layer.featureCount() == 1
    circle = layers.circle_layer(gent_zone)
    assert circle.featureCount() == 1
    cpts = [Cpt("k1", "S1", 104300.0, 192500.0, 8.0, 20.0, "2020-01-01", "continu elektrisch", None, None, None,
                "https://www.dov.vlaanderen.be/data/sondering/k1", 12.0)]
    pts = layers.points_layer("sondering", cpts)
    assert pts.featureCount() == 1
    f = next(pts.getFeatures())
    assert f["nummer"] == "S1" and f["url"].endswith("/k1") and abs(f["afstand_m"] - 12.0) < 1e-9


def test_the_search_area_covers_the_whole_zone(qgs_app):
    """De zoekstraallaag is het gebied dat de kern echt doorzocht - de kern vraagt DOV om
    DWITHIN(zone, radius_m), dus de zone plus radius_m rondom, niet een cirkel om het
    zwaartepunt. Bij deze L valt de verste hoek buiten zo'n cirkel."""
    from desktopstudie.qgis import layers

    area = next(layers.circle_layer(_zone(L_RING, L_RADIUS)).getFeatures()).geometry()
    assert area.contains(_polygon(L_RING))


def test_the_search_area_reaches_exactly_the_radius_from_the_zone_edge(qgs_app):
    """Precies radius_m vanaf de zonerand, gemeten loodrecht op die rand: 1 m ervoor ligt erin,
    1 m erna erbuiten. Een cirkel om het zwaartepunt haalt hier geen van beide."""
    from qgis.core import QgsGeometry, QgsPointXY

    from desktopstudie.qgis import layers

    area = next(layers.circle_layer(_zone(L_RING, L_RADIUS)).getFeatures()).geometry()
    y = 192500.0  # midden van de onderste balk, ruim van de hoeken vandaan
    inside = QgsGeometry.fromPointXY(QgsPointXY(L_WEST_EDGE_X - (L_RADIUS - 1.0), y))
    outside = QgsGeometry.fromPointXY(QgsPointXY(L_WEST_EDGE_X - (L_RADIUS + 1.0), y))
    assert area.contains(inside)
    assert not area.contains(outside)


def test_the_search_area_does_not_bulge_where_the_zone_is_narrow(qgs_app):
    """De valkuil van de zwaartepuntcirkel: bij een langgerekte zone rekt die ver voorbij de
    smalle kant. 480 m boven de bovenrand van de onderste balk hoort buiten de zoekstraal van
    250 m te liggen - daar zocht de kern niet."""
    from qgis.core import QgsGeometry, QgsPointXY

    from desktopstudie.qgis import layers

    area = next(layers.circle_layer(_zone(L_RING, L_RADIUS)).getFeatures()).geometry()
    far_north_of_the_lower_bar = QgsGeometry.fromPointXY(QgsPointXY(104500.0, 193000.0 + 480.0))
    assert not area.contains(far_north_of_the_lower_bar)


def test_the_search_area_layer_has_a_stable_name(qgs_app, gent_zone):
    """De naam mag niet met de straal meebewegen: de layout en het GeoPackage verwijzen ernaar."""
    from desktopstudie.qgis import layers

    assert layers.circle_layer(gent_zone).name() == "Zoekstraal"
    assert next(layers.circle_layer(gent_zone).getFeatures())["straal_m"] == 500.0


def test_line_layer_is_empty_without_a_section_line(qgs_app, gent_zone):
    """`zone.section_line` wordt pas door de kern gevuld; zonder lijn blijft de laag leeg
    maar geldig, zodat de kaartpagina hem altijd kan toevoegen."""
    from desktopstudie.qgis import layers

    assert layers.line_layer(gent_zone).featureCount() == 0
    gent_zone.section_line = ((104276.0, 192506.0), (104376.0, 192506.0))
    line = layers.line_layer(gent_zone)
    assert line.isValid() and line.featureCount() == 1
    assert next(line.getFeatures())["naam"] == "A-A'"


def test_point_symbols_and_labels_are_pinned_per_kind(qgs_app):
    """Marker, kleur en de maateenheden staan vast: zonder expliciete eenheid erft een symbool
    de projectinstelling en wordt de kaart op de ene machine anders dan op de andere."""
    from qgis.core import Qgis

    from desktopstudie.qgis import layers

    expected = {"sondering": ("circle", "#1f4e79"), "boring": ("square", "#c00000"),
                "peilput": ("triangle", "#2e75b6")}
    for kind, (marker, colour) in expected.items():
        layer = layers.points_layer(kind, [])
        symbol = layer.renderer().symbol()
        assert symbol.symbolLayer(0).properties()["name"] == marker, kind
        assert symbol.color().name() == colour, kind
        assert symbol.sizeUnit() == Qgis.RenderUnit.Millimeters, kind
        settings = layer.labeling().settings()
        assert settings.fieldName == "nummer", kind
        assert settings.format().sizeUnit() == Qgis.RenderUnit.Points, kind
        assert layer.labelsEnabled(), kind


def test_the_depth_field_says_it_doubles_as_the_filter_base(qgs_app):
    """diepte_m draagt voor een peilput de filterbasis; de alias maakt dat zichtbaar in de
    attributentabel en in het GeoPackage."""
    from desktopstudie.qgis import layers

    layer = layers.points_layer("peilput", [])
    assert layer.attributeAlias(layer.fields().indexOf("diepte_m")) == "diepte / filterbasis (m)"


def test_groups_and_geopackage(qgs_app, gent_zone, tmp_path):
    from qgis.core import QgsProject, QgsVectorLayer

    from desktopstudie.core.model import Cpt
    from desktopstudie.qgis import layers

    project = QgsProject()
    zone = layers.zone_layer(gent_zone)
    cpts = [Cpt("k1", "S1", 104300.0, 192500.0, 8.0, 20.0, "2020-01-01", "continu elektrisch", None, None, None,
                "https://www.dov.vlaanderen.be/data/sondering/k1", 12.0)]
    points = layers.points_layer("sondering", cpts)
    layers.add_group(project, "5 Grondonderzoek", [zone, points])
    assert project.layerTreeRoot().findGroup("5 Grondonderzoek") is not None

    gpkg = tmp_path / "studie.gpkg"
    layers.write_geopackage([zone, points], gpkg)
    assert gpkg.exists() and gpkg.stat().st_size > 1000
    for name, count in (("Onderzoekszone", 1), ("Sonderingen", 1)):
        reopened = QgsVectorLayer(f"{gpkg}|layername={name}", name, "ogr")
        assert reopened.isValid(), name
        assert reopened.featureCount() == count, name


def _study_gpkg(gent_zone, tmp_path):
    """Het GeoPackage zoals de pijplijn het achterlaat: zone, doorsnedelijn, de drie proefsoorten
    en de zoekstraal."""
    from desktopstudie.core.model import Cpt
    from desktopstudie.qgis import layers

    cpts = [Cpt("k1", "S1", 104300.0, 192500.0, 8.0, 20.0, "2020-01-01", "continu elektrisch", None, None, None,
                "https://www.dov.vlaanderen.be/data/sondering/k1", 12.0)]
    gent_zone.section_line = ((104226.0, 192406.0), (104426.0, 192606.0))
    written = [layers.zone_layer(gent_zone), layers.line_layer(gent_zone),
               layers.points_layer("sondering", cpts), layers.points_layer("boring", []),
               layers.points_layer("peilput", []), layers.circle_layer(gent_zone)]
    gpkg = tmp_path / "studie.gpkg"
    layers.write_geopackage(written, gpkg)
    return gpkg


@pytest.fixture
def offline_wms(monkeypatch, gent_zone):
    """Een memory-laag in plaats van een echte WMS-laag: de offline suite mag geen
    GetCapabilities doen, en waar de laag vandaan komt is voor deze tests niet de vraag."""
    from desktopstudie.qgis import layers

    built = []

    def fake_wms(entry):
        built.append(entry.id)
        layer = layers.zone_layer(gent_zone)
        layer.setName(entry.title)
        return layer

    monkeypatch.setattr(layers, "wms_layer", fake_wms)
    return built


def test_the_standalone_project_carries_the_study_layers_in_their_groups(qgs_app, gent_zone, tmp_path,
                                                                        offline_wms):
    """Het tweede product van een studie is een project dat de gebruiker later opent zonder de
    plugin. De lagen komen dan uit het GeoPackage - het geheugen is dan leeg - en staan in
    dezelfde groepen als tijdens de studie."""
    from desktopstudie.qgis import layers

    gpkg = _study_gpkg(gent_zone, tmp_path)

    project = layers.standalone_project(gpkg, {"ligging": "1 Ligging en topografie"})

    names = [group.name() for group in project.layerTreeRoot().findGroups()]
    assert names == ["1 Ligging en topografie", "4 Onderzoekszone en doorsnede", "5 Grondonderzoek DOV"]
    assert project.crs().authid() == "EPSG:31370"
    found = {layer.name(): layer for layer in project.mapLayers().values()}
    for name, count in (("Onderzoekszone", 1), ("Doorsnedelijn", 1), ("Sonderingen", 1),
                        ("Boringen", 0), ("Peilputten", 0), ("Zoekstraal", 1)):
        assert name in found, sorted(found)
        assert found[name].isValid(), name
        assert found[name].featureCount() == count, name


def test_the_standalone_layers_keep_the_house_style(qgs_app, gent_zone, tmp_path, offline_wms):
    """Dezelfde symbolen als op de kaartpagina's: een studie die er in QGIS anders uitziet dan in
    het rapport, laat de lezer twee kaarten vergelijken die niet dezelfde zijn."""
    from qgis.core import Qgis

    from desktopstudie.qgis import layers

    gpkg = _study_gpkg(gent_zone, tmp_path)

    project = layers.standalone_project(gpkg, {})

    found = {layer.name(): layer for layer in project.mapLayers().values()}
    cpt_symbol = found["Sonderingen"].renderer().symbol()
    assert cpt_symbol.symbolLayer(0).properties()["name"] == "circle"
    assert cpt_symbol.color().name() == "#1f4e79"
    assert cpt_symbol.sizeUnit() == Qgis.RenderUnit.Millimeters
    assert found["Sonderingen"].labelsEnabled()
    zone_outline = found["Onderzoekszone"].renderer().symbol().symbolLayer(0).properties()["outline_color"]
    assert zone_outline.startswith("255,0,0")
    assert found["Zoekstraal"].renderer().symbol().symbolLayer(0).properties()["outline_style"] == "dash"


def test_a_layer_missing_from_the_geopackage_is_reported_not_guessed(qgs_app, gent_zone, tmp_path,
                                                                    offline_wms):
    """Een half of ouder GeoPackage mist lagen. Dan hoort de rest gewoon te laden, mét een
    WARNING per laag die er niet is - stil overslaan laat de gebruiker zoeken."""
    from desktopstudie.core.logging_util import Log
    from desktopstudie.qgis import layers

    gpkg = tmp_path / "half.gpkg"
    layers.write_geopackage([layers.zone_layer(gent_zone)], gpkg)
    lines = []

    project = layers.standalone_project(gpkg, {}, log=Log("layers", lines.append, scope="qgis"))

    assert [layer.name() for layer in project.mapLayers().values()] == ["Onderzoekszone"]
    warnings = [line for line in lines if "WARNING" in line]
    assert any("Doorsnedelijn" in line for line in warnings), lines
    assert any("Peilputten" in line for line in warnings), lines


def test_the_standalone_project_can_be_written_and_read_back(qgs_app, gent_zone, tmp_path, offline_wms):
    """Het bestand is het product, niet het object in het geheugen: wat erin staat moet in een
    verse QGIS weer opengaan, met de groepen en de lagen erin."""
    from qgis.core import QgsProject

    from desktopstudie.qgis import layers

    gpkg = _study_gpkg(gent_zone, tmp_path)
    path = tmp_path / "studie.qgz"
    assert layers.standalone_project(gpkg, {}).write(str(path))

    reread = QgsProject()
    assert reread.read(str(path)), reread.error()
    assert [group.name() for group in reread.layerTreeRoot().findGroups()] == \
           ["4 Onderzoekszone en doorsnede", "5 Grondonderzoek DOV"]
    assert sorted(layer.name() for layer in reread.mapLayers().values()) == \
           ["Boringen", "Doorsnedelijn", "Onderzoekszone", "Peilputten", "Sonderingen", "Zoekstraal"]


def test_write_geopackage_refuses_an_empty_list(qgs_app, tmp_path):
    """Een leeg GeoPackage is geen geldig resultaat: dan is er eerder in de pijplijn iets fout
    gegaan en dat moet hier stuklopen, niet stil een bestand van niks opleveren."""
    from desktopstudie.qgis import layers

    with pytest.raises(ValueError):
        layers.write_geopackage([], tmp_path / "studie.gpkg")


def test_write_geopackage_reports_the_writers_own_message(qgs_app, gent_zone, tmp_path):
    """Schrijven mag nooit stil mislukken, en de fout van de writer zelf moet in de melding
    staan - niet alleen onze eigen tekst eromheen."""
    from desktopstudie.qgis import layers

    with pytest.raises(RuntimeError) as err:
        layers.write_geopackage([layers.zone_layer(gent_zone)], tmp_path / "geen" / "map" / "studie.gpkg")
    message = str(err.value)
    assert "Onderzoekszone" in message
    assert "OGR" in message or "failed" in message


def test_a_locked_geopackage_says_what_to_do_about_it(qgs_app):
    """Het gewone geval bij herhaald draaien: de vorige studie staat nog open in QGIS en houdt
    het bestand vast. Dan moet de melding zeggen wat de gebruiker moet doen."""
    from desktopstudie.qgis import layers

    locked = layers.gpkg_failure_message("Sonderingen", "ERROR: database is locked")
    assert "sluit de lagen van een vorige studie in QGIS en probeer opnieuw" in locked
    exists = layers.gpkg_failure_message("Sonderingen", "Layer Sonderingen already exists")
    assert "sluit de lagen van een vorige studie in QGIS en probeer opnieuw" in exists
    other = layers.gpkg_failure_message("Sonderingen", "OGR error: disk full")
    assert "probeer opnieuw" not in other and "disk full" in other


@pytest.mark.live
def test_live_wms_layer_is_valid(qgs_app):
    from desktopstudie.core import catalogue
    from desktopstudie.qgis import layers

    lyr = layers.wms_layer(catalogue.by_id("ferraris"))
    assert lyr.isValid(), lyr.error().summary()


@pytest.mark.live
def test_live_all_enabled_wms_layers_are_valid(qgs_app):
    """Elke ingeschakelde catalogusingang moet een echte WMS-laag opleveren - dat is de enige
    controle die een verkeerde laag- of stijlnaam (gxg, pfas) opmerkt."""
    from desktopstudie.core import catalogue
    from desktopstudie.qgis import layers

    problems = []
    for entry in catalogue.entries():
        lyr = layers.wms_layer(entry)
        if not lyr.isValid():
            problems.append(f"{entry.id}: ongeldig - {lyr.error().summary()}")
        elif abs(lyr.opacity() - entry.opacity) > 1e-9:
            problems.append(f"{entry.id}: dekking {lyr.opacity()} != {entry.opacity}")
    assert not problems, "\n".join(problems)


@pytest.mark.live
def test_live_wcs_layer_is_valid(qgs_app):
    from qgis.core import QgsPointXY

    from desktopstudie.core.catalogue import DHMV_WCS_COVERAGE, DHMV_WCS_URL
    from desktopstudie.qgis import layers

    lyr = layers.wcs_layer(DHMV_WCS_URL, DHMV_WCS_COVERAGE, "DHMV II DTM 1 m")
    assert lyr.isValid(), lyr.error().summary()
    assert lyr.providerType() == "wcs"
    assert lyr.extent().contains(QgsPointXY(*GENT)), lyr.extent().toString(0)


def test_the_standalone_project_reuses_the_wms_layers_it_is_given(qgs_app, gent_zone, tmp_path, offline_wms):
    """De pijplijn heeft de WMS-lagen al gebouwd (en dus al een GetCapabilities per kaart betaald).
    Het zelfstandige project hoort die te hergebruiken in plaats van ze nog eens op te halen."""
    from desktopstudie.qgis import layers

    gpkg = _study_gpkg(gent_zone, tmp_path)
    ready = layers.zone_layer(gent_zone)
    ready.setName("GRB-basiskaart")

    project = layers.standalone_project(gpkg, {"ligging": "1 Ligging en topografie"},
                                        wms_layers={"grb": ready})

    assert "grb" not in offline_wms, "grb stond klaar en is toch opnieuw gebouwd"
    assert "ortho" in offline_wms, "de rest hoort wel gebouwd te worden"
    names = [layer.name() for layer in project.mapLayers().values()]
    assert "GRB-basiskaart" in names
    # een kopie, geen hergebruikte pointer: het project dat wordt weggeschreven bezit zijn lagen
    assert all(layer is not ready for layer in project.mapLayers().values())


def test_only_the_investigations_with_a_figure_are_labelled_on_the_overlay(qgs_app):
    """Tweehonderd nummers over elkaar maken de overzichtskaart onleesbaar. Alleen de proeven die
    ook een figuur in het rapport hebben, krijgen een label; in QGIS blijven alle labels staan."""
    from desktopstudie.core.model import Cpt
    from desktopstudie.qgis import layers

    cpts = [Cpt(f"k{i}", f"S{i}", 104300.0 + i, 192500.0, 8.0, 20.0, "2020-01-01", "ce", None, None, None,
                f"https://dov/data/sondering/k{i}", 12.0) for i in range(3)]

    layer = layers.points_layer("sondering", cpts, figured={"k0"})

    values = sorted(feature["met_figuur"] for feature in layer.getFeatures())
    assert values == [0, 0, 1]
    assert layer.labeling().settings().fieldName == "nummer"
    assert not layer.labeling().settings().isExpression

    overlay = layers.style_points_layer(layer.clone(), "sondering", label_only_figured=True)

    settings = overlay.labeling().settings()
    assert settings.isExpression
    assert "met_figuur" in settings.fieldName and "nummer" in settings.fieldName


def test_a_peilput_keeps_its_number_on_a_report_map(qgs_app):
    """Alleen sonderingen en boringen krijgen een figuur in het rapport. Zou "label alleen wie een
    figuur heeft" ook voor peilputten gelden, dan verliezen die op elke kaartpagina hun nummer en
    is er geen enkele manier meer om een driehoekje aan de peilputtentabel te koppelen - terwijl
    het er in een zone een handvol zijn, niet tweehonderd."""
    from desktopstudie.qgis import layers

    peilput = layers.style_points_layer(layers.points_layer("peilput", []), "peilput",
                                        label_only_figured=True)
    sondering = layers.style_points_layer(layers.points_layer("sondering", []), "sondering",
                                          label_only_figured=True)

    assert peilput.labeling().settings().fieldName == "nummer"
    assert not peilput.labeling().settings().isExpression
    assert sondering.labeling().settings().isExpression
