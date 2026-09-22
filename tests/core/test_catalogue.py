from __future__ import annotations

import pytest

from desktopstudie.core import catalogue as c
from tests.core.conftest import fixture_json

FIXTURE_FOR = {
    "bodemkaart": "wfs_bodemtypes_intersects.json",
    "quartair": "wfs_quartair_samengesteld_intersects.json",
    "quartair_200k": "wfs_quartair_200k_intersects.json",
    "quartair_dikte": "wfs_quartair_isopachen_dwithin.json",
    "tertiair": "wfs_tertiair_50k_intersects.json",
    "hcov": "wfs_hcov_0100_vk_intersects.json",
    "gw_kwetsbaarheid": "wfs_gwkwb_kwbschaal_intersects.json",
    "erosie": "wfs_erosie_2014_intersects.json",
    "krimp_zwel": "gfi_krimp_zwel_hit.json",
    "ovam": "wfs_ovam_uitspraak_intersects.json",
    "grondverschuiving_gevoeligheid": "wfs_grndversch_gevoeligh_intersects.json",
    "grondverschuiving_gekarteerd": "wfs_grndversch_gekarteerd_intersects.json",
    "pfas_no_regret": "wfs_pfas_no_regret_intersects.json",
    "watertoets_pluviaal": "watertoets_fluviaal_hit.json",
    "watertoets_fluviaal": "watertoets_fluviaal_hit.json",
    "gxg_ghg": "gxg_ghg_hit.json",
    "gxg_glg": "gxg_glg_hit.json",
}


def test_fact_fields_exist_in_recorded_fixtures():
    for e in c.entries():
        if not e.fact_mode:
            continue
        assert e.id in FIXTURE_FOR, e.id
        data = fixture_json(FIXTURE_FOR[e.id])
        features = data["features"]
        assert features, f"{e.id}: fixture {FIXTURE_FOR[e.id]} has no features"
        for field_name in e.fact_fields:
            if field_name == c.DISTANCE_FIELD:
                continue  # de studie rekent dit veld zelf uit; het staat in geen enkel antwoord
            assert field_name in features[0]["properties"], f"{e.id}: missing field {field_name!r}"


def test_ids_are_unique_and_chapters_known():
    ids = [e.id for e in c.CATALOGUE]
    assert len(ids) == len(set(ids))
    assert {e.chapter for e in c.CATALOGUE} <= {"ligging", "historisch", "geologie"}


def test_enabled_entries_have_a_wms_url_and_layer():
    for e in c.entries():
        assert e.wms_url.startswith("https://"), e.id
        assert e.wms_layer, e.id


def test_ngi_historic_is_a_documented_empty_slot():
    slot = c.by_id("ngi_hist")
    assert slot.enabled is False
    assert "kaartdienst" in slot.note, "de reden hoort in de taal van de lezer te staan"


def test_fact_entries_declare_fields():
    for e in c.entries():
        if e.fact_mode == "wfs":
            assert e.wfs_typename and e.fact_fields, e.id
        if e.fact_mode == "gfi":
            assert e.fact_fields, e.id


def test_bodemkaart_fact_fields_include_texture_and_drainage_codes():
    fields = c.by_id("bodemkaart").fact_fields
    assert "Textuurklasse_code" in fields
    assert "Drainageklasse_code" in fields


def test_watertoets_labels_translate_gridcode():
    e = c.by_id("watertoets_fluviaal")
    assert e.value_labels["gridcode"]["3"].startswith("D - ")


def test_entries_are_hashable():
    entries = c.entries()
    assert len({e for e in entries}) == len(entries)
    hash(c.by_id("watertoets_fluviaal"))  # must not raise


def test_entries_filter_by_chapter_and_enabled():
    assert [e.id for e in c.entries("ligging")] == ["grb", "ortho", "ngi_topo", "dhmv_hillshade", "dhmv_dtm"]
    assert len(c.entries("historisch")) == 7
    assert len(c.entries("historisch", enabled_only=False)) == 9  # + ngi_hist and bommenkaart


def test_by_id_unknown_raises_key_error():
    with pytest.raises(KeyError):
        c.by_id("does_not_exist")


def test_every_fact_field_has_a_readable_label():
    for e in c.CATALOGUE:
        if e.fact_mode is None:
            continue
        missing = [f for f in e.fact_fields if f not in e.field_labels]
        assert not missing, f"{e.id} missing labels for {missing}"


def test_every_map_has_a_positive_scale_and_low_resolution_maps_zoom_out():
    assert all(e.scale > 0 for e in c.CATALOGUE)
    assert c.by_id("ferraris").scale > c.by_id("grb").scale
    assert c.by_id("quartair_200k").scale > c.by_id("bodemkaart").scale
    assert all(1000 <= e.scale <= 200000 for e in c.CATALOGUE)


def test_service_urls_carry_their_template_placeholders():
    assert "{model}" in c.VB_DOORPRIK_URL
    assert "{model}" in c.VB_PROFILE_URL and c.VB_PROFILE_URL.endswith("/profielbevraging/lagen")
    assert "{kind}" in c.WATERINFO_WMS_URL
    assert all(url.startswith("https://") for url in
               (c.DOV_WFS_URL, c.DOV_WMS_URL, c.GEOCODER_URL, c.VB_DOORPRIK_URL, c.VB_PROFILE_URL,
                c.WATERINFO_WMS_URL, c.DHMV_WCS_URL))


def test_every_dov_map_asks_the_service_of_its_own_workspace_by_the_layers_own_name():
    """A WMS layer costs a GetCapabilities, and the global DOV service answers with the whole
    of DOV - 1,1 MB that QGIS parses for 2,6 s per map, fifteen times a study. GeoServer serves
    every workspace at its own address (`/geoserver/<workspace>/wms`) with a capabilities of a
    few kB, on which the layer goes by its own name, without the workspace prefix (live
    2026-09-16: 0,03 s per map, identical GetMap and GetLegendGraphic bytes). The WFS typename
    keeps its prefix: that is the global WFS."""
    dov = [e for e in c.CATALOGUE if "dov.vlaanderen.be/geoserver" in e.wms_url]
    assert len(dov) == 15
    for entry in dov:
        workspace = entry.wms_url.rsplit("/geoserver/", 1)[1].split("/")[0]
        assert entry.wms_url == c.DOV_WORKSPACE_WMS_URL.format(workspace=workspace), entry.id
        assert ":" not in entry.wms_layer, entry.id
        if entry.wfs_typename:
            assert entry.wfs_typename.startswith(f"{workspace}:"), entry.id


def test_bommenkaart_is_a_documented_empty_slot_naming_the_explosives_risk():
    slot = c.by_id("bommenkaart")
    assert slot.chapter == "historisch"
    assert slot.enabled is False
    assert "geen open data" in slot.note and "kaartdienst" in slot.note
    assert "explosieven" in slot.note


def test_the_pfas_map_names_ovam_as_its_source():
    entry = c.by_id("pfas_no_regret")
    assert entry.chapter == "geologie"
    assert entry.attribution == "OVAM / Vlaamse overheid via DOV"
    # no_regret_zones is a STYLE of pfas:no_regret_huidig, not a WMS layer of its own; on the
    # workspace service the layer goes by its own name
    assert entry.wms_url == "https://www.dov.vlaanderen.be/geoserver/pfas/wms"
    assert entry.wms_layer == "no_regret_huidig"
    assert entry.wfs_typename == "pfas:no_regret_huidig"


def test_the_landslide_maps_expose_the_class_and_the_report_link():
    assert c.by_id("grondverschuiving_gevoeligheid").fact_fields == ("gevoelighd", "klasse")
    assert c.by_id("grondverschuiving_gevoeligheid").legend is True
    assert "rapport" in c.by_id("grondverschuiving_gekarteerd").fact_fields
    assert c.by_id("grondverschuiving_gekarteerd").scale == 10000


def test_the_label_tables_of_a_catalogue_entry_cannot_be_written_into():
    # The catalogue is module-level shared state: a caller that wrote into a label table would
    # change the map for every later study in the same QGIS session. The write has to fail here,
    # not show up as a wrong header three reports later.
    entry = c.by_id("watertoets_fluviaal")
    with pytest.raises(TypeError):
        entry.value_labels["gridcode"]["0"] = "iets anders"
    with pytest.raises(TypeError):
        entry.value_labels["gridcode"] = {}
    with pytest.raises(TypeError):
        entry.field_labels["gridcode"] = "Iets anders"
    assert entry.value_labels["gridcode"]["0"].startswith("A - ")
    assert entry.field_labels["gridcode"] == "Klasse"


def test_a_catalogue_entry_without_label_tables_still_reads_like_a_mapping():
    entry = c.by_id("grb")
    assert entry.value_labels == {} and entry.field_labels == {}
    assert entry.value_labels.get("x", {}).get("y") is None


def test_the_gxg_map_names_the_real_layer_and_carries_the_style():
    # gxg:gxg is a STYLE of gxg:ghg_mmv_main, not a layer of its own: a GetMap on gxg:gxg answers
    # with a ServiceException, exactly like pfas:no_regret_zones (both verified live 2026-09-15).
    entry = c.by_id("gxg_ghg")
    assert entry.wms_url == "https://www.dov.vlaanderen.be/geoserver/gxg/wms"
    assert entry.wms_layer == "ghg_mmv_main"
    assert entry.wms_style == "gxg:gxg"


def test_the_groundwater_level_maps_are_a_highest_and_a_lowest_one():
    # GxG is a pair: the mean highest (GHG) and the mean lowest (GLG) groundwater level. One map
    # titled "GxG" hides which of the two the reader is looking at, so each gets its own entry and
    # its own page. Both draw with the same named style (live GetMap 2026-09-15: gxg:glg_mmv_main
    # + gxg:gxg -> HTTP 200 image/png).
    ghg, glg = c.by_id("gxg_ghg"), c.by_id("gxg_glg")
    assert ghg.title == "Gemiddeld hoogste grondwaterstand (GHG)"
    assert glg.title == "Gemiddeld laagste grondwaterstand (GLG)"
    assert glg.wms_layer == "glg_mmv_main"
    assert glg.wms_style == "gxg:gxg"
    assert glg.chapter == ghg.chapter == "geologie"
    assert glg.attribution == ghg.attribution and glg.licence == ghg.licence
    assert glg.legend is False and glg.scale == 25000  # de kleurbalk staat onder de kaart
    # they stay neighbours, so the report shows the highest and the lowest level side by side
    ids = [e.id for e in c.entries("geologie")]
    assert ids.index("gxg_glg") == ids.index("gxg_ghg") + 1


def test_a_map_without_an_explicit_style_asks_the_service_for_its_default():
    # An empty styles parameter means "the layer default"; only maps whose wanted rendering is a
    # named style fill wms_style in.
    assert c.by_id("grb").wms_style == ""
    assert [e.id for e in c.entries() if e.wms_style] == ["gxg_ghg", "gxg_glg"]


def test_a_map_id_says_which_of_the_two_gxg_levels_it_is():
    # "gxg" alone names the pair, not a map: with GHG and GLG side by side, an id that could mean
    # either is the one thing a reader of the report tree cannot resolve.
    with pytest.raises(KeyError):
        c.by_id("gxg")
    assert {"gxg_ghg", "gxg_glg"} <= {e.id for e in c.entries("geologie")}


def test_every_map_carries_legend_options_for_the_legend_image():
    # The legend is fetched as a picture (GetLegendGraphic). Without LEGEND_OPTIONS GeoServer
    # answers with one endless column of classes - a strip no page can hold - so every entry
    # carries a column layout and a readable font size.
    for entry in c.CATALOGUE:
        assert "columns:" in entry.legend_options, entry.id
        assert "fontSize:" in entry.legend_options, entry.id


def test_the_soil_map_has_no_legend_page():
    # The soil map legend lists every soil series in Flanders (hundreds of classes): on paper it
    # is unreadable and pages long. The fact table names the soil types inside the zone, which is
    # what the reader actually needs.
    soil = c.by_id("bodemkaart")
    assert soil.legend is False
    assert soil.fact_mode == "wfs" and soil.fact_fields


def test_the_maps_with_a_degenerate_legend_have_no_legend_page():
    # HCOV 0100 and the composite quartair map answer GetLegendGraphic with a 20x20 stamp that
    # names nothing: a blank page with a coloured square on it. Their fact tables carry the units
    # in the zone, so the page is dropped rather than printed empty.
    for map_id in ("hcov", "quartair"):
        entry = c.by_id(map_id)
        assert entry.legend is False, map_id
        assert entry.fact_mode == "wfs" and entry.fact_fields, map_id


def test_the_height_model_has_no_legend_page():
    # The DHMV legend is a colour ramp of 27 x 18 mm with two numbers on it (300 to -50). A whole
    # sheet for that is a sheet the reader turns past; what the colours mean - height in mTAW -
    # belongs in a sentence, not on a page of its own.
    assert c.by_id("dhmv_dtm").legend is False


GUIDED_MAPS = ("bodemkaart", "quartair", "quartair_200k", "tertiair", "dhmv_dtm", "gw_kwetsbaarheid",
               "watertoets_pluviaal", "watertoets_fluviaal", "erosie", "krimp_zwel", "pfas_no_regret",
               "grondverschuiving_gevoeligheid", "grondverschuiving_gekarteerd", "hcov")


def test_the_maps_whose_codes_need_explaining_carry_a_reading_guide():
    # "OB", "22026", "GeVl", "Dc": every one of these is unreadable without a sentence telling the
    # reader how the code is built. The guide is short on purpose - three to five sentences - and
    # names its own source, so a reader who wants the whole legend can go there.
    for map_id in GUIDED_MAPS:
        guide = c.by_id(map_id).reading_guide
        assert guide, map_id
        sentences = guide.count(". ") + 1  # de laatste zin sluit op een punt of op een URL
        assert 3 <= sentences <= 5, f"{map_id}: {sentences} zinnen"


def test_a_reading_guide_that_names_a_legend_names_a_dov_page():
    # The three maps whose legend runs to hundreds of classes point at the official page instead of
    # repeating it; the others explain their handful of classes in the guide itself.
    for map_id in ("bodemkaart", "quartair", "quartair_200k", "tertiair"):
        assert "https://www.dov.vlaanderen.be/page/" in c.by_id(map_id).reading_guide, map_id


def test_a_map_without_a_guide_simply_has_none():
    # Ferraris needs no reading guide: it is a picture, not a coded map.
    assert c.by_id("ferraris").reading_guide == ""


def test_the_legend_options_ask_for_a_readable_font_and_two_columns():
    # Four columns of 7 pt is what fits a screen, not what a reader can follow on paper: the class
    # names run into each other and the swatches are the size of a full stop. Two columns of 9 pt
    # with forceLabels (GeoServer otherwise drops the label of a single-class layer) make a legend
    # that is taller - and taller is exactly what the page-high strips are for.
    assert c.MapEntry.legend_options == "columns:2;columnheight:1100;fontSize:9;forceLabels:on"
    for entry in c.CATALOGUE:
        assert "fontSize:9" in entry.legend_options, entry.id


def test_a_sparse_theme_asks_for_a_base_map_under_it_and_a_full_cover_map_does_not():
    """Een thema dat maar enkele procenten van de uitsnede bedekt - gekarteerde
    grondverschuivingen, watertoets, PFAS - levert zonder ondergrond een wit blad met een rood
    cirkeltje: de lezer ziet niet waar iets ligt. Die kaarten vragen de basiskaart eronder; een
    kaart die de hele uitsnede vult (bodemkaart, tertiair) zou ze alleen maar verbergen.

    Een kaart die de uitsnede wel vult maar DOORZICHTIG genoeg getekend wordt hoort er ook bij:
    krimp-zwel is een veld van zes klassen in grote blokken, en zonder straten eronder is het een
    blad kleur waar niets aan af te lezen valt. De regel is niet "dun thema", maar "de lezer ziet
    de ondergrond": doordat ze dun is, of doordat het thema eroverheen doorzichtig is.

    Gemeten op de Gent-uitsnede (2026-09-17, doorzichtig deel van de GetMap): gekarteerde
    grondverschuivingen 100 %, erosie 100 %, watertoets fluviaal 100 %, dikte van het Quartair
    100 %, watertoets pluviaal 91 %, OVAM 69 %, PFAS 61 % - tegen 0 % voor de bodemkaart, het
    Tertiair, HCOV en de kwetsbaarheidskaart.
    """
    from desktopstudie.core import catalogue

    over = {e.id for e in catalogue.entries() if e.backdrop}
    assert over == {"quartair_dikte", "watertoets_pluviaal", "watertoets_fluviaal", "erosie",
                    "ovam", "grondverschuiving_gevoeligheid", "grondverschuiving_gekarteerd",
                    "pfas_no_regret", "krimp_zwel"}
    for map_id in ("grb", "ortho", "ferraris", "dhmv_dtm", "bodemkaart", "tertiair", "hcov"):
        assert not catalogue.by_id(map_id).backdrop, map_id


def test_the_base_map_is_named_once():
    """De kaart die als ondergrond dient en de kaart die in het project aanstaat zijn dezelfde;
    twee constanten met dezelfde waarde drijven uit elkaar."""
    from desktopstudie.core import catalogue

    assert catalogue.BASE_MAP_ID == "grb"
    assert catalogue.by_id(catalogue.BASE_MAP_ID).chapter == "ligging"


def test_the_groundwater_levels_ask_the_service_for_their_value():
    """GHG en GLG droegen een kaart zonder getal en zonder legenda. De grondwaterstand is voor een
    geotechnische studie een van de belangrijkste cijfers, dus vraagt de kaart haar waarde op bij
    de dienst - met de veldnamen die de dienst echt teruggeeft.

    Live geverifieerd op 2026-09-17 (GetFeatureInfo op het representatieve punt van de Gent-zone,
    104326.8 / 192506.7, EPSG:31370): `GHG-waarde_m-mv` = 2.85 en `GLG-waarde_m-mv` = 3.54, met de
    standaardafwijking en de twee grenzen van het 80 %-betrouwbaarheidsinterval ernaast. De naam
    zegt de eenheid: meter ONDER MAAIVELD, geen peil in mTAW.
    """
    from desktopstudie.core import catalogue

    ghg = catalogue.by_id("gxg_ghg")
    assert ghg.fact_mode == "gfi"
    assert ghg.fact_fields == ("GHG-waarde_m-mv", "Standaardafwijking_GHG_m",
                               "Onderkant_80_procent_betrouwbaarheidsinterval_GHG_m-mv",
                               "Bovenkant_80_procent_betrouwbaarheidsinterval_GHG_m-mv")
    assert "m onder maaiveld" in ghg.field_labels["GHG-waarde_m-mv"]
    glg = catalogue.by_id("gxg_glg")
    assert glg.fact_fields[0] == "GLG-waarde_m-mv"
    for entry in (ghg, glg):
        assert "grondwaterstand" in entry.reading_guide
        assert "onder het maaiveld" in entry.reading_guide
        assert entry.ramp, "de klassenbalk hoort onder de kaart, niet op een legendablad"
        assert not entry.legend, "en dus niet ook nog als eigen legendablad"


def test_only_the_maps_whose_legend_is_a_colour_bar_ask_for_one():
    """Een kleurbalk onder de kaart is voor een kaart met een doorlopende schaal; een kaart met
    klassen in een tabel heeft er geen."""
    from desktopstudie.core import catalogue

    assert {e.id for e in catalogue.entries() if e.ramp} == {"dhmv_dtm", "gxg_ghg", "gxg_glg"}


def test_a_map_carries_the_answer_format_its_own_service_speaks():
    """Niet elke dienst kent hetzelfde antwoordformaat voor GetFeatureInfo. De GeoServer van DOV
    antwoordt op `application/json` en geeft op `application/geo+json` een ServiceExceptionReport;
    de ArcGIS-dienst van de watertoets kent juist wel `application/geo+json`. Live gecontroleerd op
    2026-09-17, beide diensten en beide formaten - dus reist het formaat mee met de kaart.
    """
    from desktopstudie.core import catalogue

    assert catalogue.by_id("gxg_ghg").gfi_format == "application/json"
    assert catalogue.by_id("gxg_glg").gfi_format == "application/json"
    assert catalogue.by_id("watertoets_pluviaal").gfi_format == "application/geo+json"


def test_a_line_layer_asks_for_the_nearest_feature_instead_of_an_overlap():
    """De isopachen van het Quartair zijn CONTOURLIJNEN, geen vlakken: een INTERSECTS met een
    zonecirkel van 50 m raakt er nooit een, dus wordt er met DWITHIN gezocht. Op de 50 000-laag
    die DOV zelf tekent liggen ze wel ter plaatse - live 2026-09-20 rond het Gent-testpunt vier
    lijnen binnen 300 m (67 m / 5 m, 71 m / 10 m, 146 m / 2,5 m, 270 m / 2,5 m) - dus hoeft de
    straal niet ruim te zijn en kan de kaart op perceelschaal staan."""
    from desktopstudie.core import catalogue

    entry = catalogue.by_id("quartair_dikte")
    assert entry.fact_within_m == 2000.0
    assert entry.scale == 25000
    assert "Dikte_Quartair_m" in entry.fact_fields and "afstand_m" in entry.fact_fields
    # de andere kaarten zijn vlakken en blijven op overlap zoeken
    assert catalogue.by_id("bodemkaart").fact_within_m is None
    assert catalogue.by_id("tertiair").fact_within_m is None


def test_the_isopach_guide_describes_the_map_the_reader_now_gets():
    """De leeswijzer beschreef de grove reeks: lijnen in stappen van vijf meter die "zelden binnen
    het kaartbeeld" liggen, en een tabel met afstanden. Alle drie zijn niet meer waar - de
    kartering op 1:50 000 tekent contouren ter plaatse, met de dikte op de lijn zelf."""
    from desktopstudie.core import catalogue

    guide = catalogue.by_id("quartair_dikte").reading_guide

    assert "zelden" not in guide, "de lijnen liggen hier wel in beeld"
    assert "stappen van vijf meter" not in guide
    assert "op de lijn" in guide, "de dikte staat op de contour zelf"
    assert "G3Dv3" in guide, "en de modelwaarde blijft uitgelegd"


def test_the_isopachs_ask_for_their_own_lettering():
    """De dienst tekent de dikte wel op de lijn, maar dun, klein en grijs: boven een drukke
    GRB-ondergrond is dat onleesbaar. De laag adverteert maar een stijl en geen variant met halo,
    dus vraagt de kaart haar eigen belettering aan met een SLD in de GetMap - dezelfde lijnen, een
    vette letter met een WITTE halo eromheen, langs de lijn in plaats van erdoorheen.

    De naam in de NamedLayer is de kale laagnaam: met het workspace-voorvoegsel erbij vindt
    GeoServer de laag niet en valt hij stilzwijgend terug op zijn eigen stijl (live 2026-09-21:
    byte voor byte hetzelfde beeld als zonder SLD)."""
    from desktopstudie.core import catalogue

    sld = catalogue.by_id("quartair_dikte").sld_body

    assert sld, "de isopachen vragen hun eigen belettering"
    assert "<Name>qisopachen_quartair_50k</Name>" in sld, "kale laagnaam, geen workspace ervoor"
    assert "<Halo>" in sld and "#FFFFFF" in sld, "witte halo rond de letters"
    assert "followLine" in sld, "het getal volgt de lijn"
    assert "Dikte_Quartair_m" in sld
    assert all(entry.sld_body == "" for entry in catalogue.CATALOGUE
               if entry.id != "quartair_dikte"), "alleen deze kaart heeft het nodig"


def test_the_shrink_swell_map_asks_for_its_own_class_not_an_index_of_units():
    """De kaart gaat over een gevoeligheidsklasse en die stond nergens in het rapport. Ze werd
    bevraagd via `plastische_gronden:IndexPlastisch`, een index van de G3Dv3-eenheden die
    beoordeeld zijn - niet van de gevoeligheid. Die index antwoordt alleen waar zo'n eenheid
    ligt, dus zweeg het rapport in Brasschaat (klasse 1) en in Brugge (klasse 4, hoog) en gaf het
    in Wervik een eenheidsnaam in plaats van de klasse.

    Live geverifieerd op 2026-09-21, GetFeatureInfo op `plastische_gronden:krimp_zwel` in
    `application/json` (`application/geo+json` geeft een ServiceExceptionReport):
    `Categorie_gevoeligheid` = 1 op 157084,4/221428,5 (Brasschaat), 4 op 67624,8/212695,4 (Brugge)
    en 2 op 57611,6/165524,9 (Wervik). De legenda van de dienst noemt 0 niet-ingedeeld, 1 zeer
    laag, 2 laag, 3 matig, 4 hoog, 5 zeer hoog.
    """
    from desktopstudie.core import catalogue

    entry = catalogue.by_id("krimp_zwel")
    assert entry.fact_mode == "gfi", "de klasse staat op de kaart zelf, niet in een index"
    assert entry.wfs_typename is None
    assert entry.gfi_format == "application/json"
    assert entry.fact_fields == ("Categorie_gevoeligheid",)
    labels = entry.value_labels["Categorie_gevoeligheid"]
    assert labels["4"] == "hoog" and labels["0"] == "niet-ingedeeld"
    assert "zeer hoog" in entry.reading_guide and "niet-ingedeeld" in entry.reading_guide


def test_the_shrink_swell_map_is_drawn_to_be_read():
    """"beetje uitzoomen voor krimp zwel? en wat meer doorzichtig?" - drie dingen tegelijk, en
    alle drie op het beeld beoordeeld (Wervik, 57611,6/165524,9, 2026-09-21).

    De ondergrond: zonder die kaart was het blad zes vlakken kleur zonder een straat om ze aan op
    te hangen. Doorzichtigheid: `opacity` werd tot nu toe alleen toegepast waar er een ondergrond
    onder ligt (`layout._over_backdrop`), dus op het blad deed de 0.7 van deze kaart niets; met
    ondergrond telt ze wel, en op 0.6 lezen straten, gebouwen en de Leie door terwijl klasse 2 en
    klasse 3 nog uit elkaar te houden zijn (op 0.5 lopen die twee in elkaar). Schaal: op 1:35 000
    staat het patroon in beeld - het rode blok ten noorden, de groene vallei - terwijl de plek
    zelf nog herkenbaar is; op 1:50 000 wordt de zone een stip.
    """
    from desktopstudie.core import catalogue

    entry = catalogue.by_id("krimp_zwel")
    assert entry.backdrop, "zonder ondergrond hangen de klassen aan niets"
    assert entry.opacity == 0.6
    assert entry.scale == 35000


def test_the_shrink_swell_map_says_how_coarsely_to_ask_it():
    """De klassenkaart ligt op een rooster van 100 m en antwoordt niets als ze op een meter per
    beeldpunt bevraagd wordt (live 2026-09-21, drie punten). Ze zegt dat zelf, zodat de fijne
    kaarten - GHG en GLG - op hun eigen rooster blijven: grover bevraagd verschuift de GLG van
    3,54 naar 3,52 m."""
    from desktopstudie.core import catalogue

    assert catalogue.by_id("krimp_zwel").gfi_m_per_pixel == 10.0
    for map_id in ("gxg_ghg", "gxg_glg", "watertoets_fluviaal", "watertoets_pluviaal"):
        assert catalogue.by_id(map_id).gfi_m_per_pixel == 0.0, map_id
