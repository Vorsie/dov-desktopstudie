"""De kaartlagen die een collega op 2026-09-23 doorstuurde, uit de cursus grondonderzoek.

Elke laagnaam hieronder komt uit GetCapabilities van de dienst zelf en elke veldnaam uit
DescribeFeatureType, live bevraagd op 2026-10-04. Dat is niet overdreven zorgvuldig: de
doorgestuurde tabel noemde vier lagen die niet bestaan, en een laagnaam die de dienst niet kent
levert geen fout maar een leeg kaartbeeld.

De orthofoto's worden hier als REGEL getest en niet als lijst - "elk winterjaar van 2012 tot 2025
heeft een entry waarvan de laag OMWRGB<jj>VL heet" - want een test die de verwachting uit dezelfde
tabel haalt als de code bewijst niets.
"""
from __future__ import annotations

import pytest

from desktopstudie.core import catalogue as c
from desktopstudie.core.services.dov_wfs import DOV_WFS_URL

OMW_WMS = "https://geo.api.vlaanderen.be/OMW/wms"
OMZ_WMS = "https://geo.api.vlaanderen.be/OMZ/wms"
MERCATOR = "https://www.mercator.vlaanderen.be/raadpleegdienstenmercatorpubliek"
VHA_WFS = "https://geo.api.vlaanderen.be/VHAWaterlopen/wfs"
# De zomerreeks is niet jaarlijks: de dienst heeft 09, 12, 15, 18, 21 en 24 en niets daartussen.
ZOMERJAREN = (2009, 2012, 2015, 2018, 2021, 2024)


@pytest.mark.parametrize("jaar", range(2012, 2026))
def test_elk_winterjaar_van_2012_tot_2025_is_een_orthofoto(jaar):
    entry = c.by_id(f"ortho_omw_{jaar}")

    assert entry.wms_url == OMW_WMS
    assert entry.wms_layer == f"OMWRGB{jaar % 100:02d}VL"
    assert entry.chapter == "historisch"
    assert str(jaar) in entry.title, "de lezer moet het jaar op het blad zien"


@pytest.mark.parametrize("jaar", ZOMERJAREN)
def test_elke_zomeropname_van_de_dienst_is_een_orthofoto(jaar):
    entry = c.by_id(f"ortho_omz_{jaar}")

    assert entry.wms_url == OMZ_WMS
    assert entry.wms_layer == f"OMZRGB{jaar % 100:02d}VL"
    assert entry.chapter == "historisch"


def test_de_winteropname_van_tien_centimeter_staat_op_haar_eigen_dienst():
    """OGW is een aparte dienst met een aparte laagnaam; de mail gaf er geen laag bij."""
    entry = c.by_id("ortho_ogw_2013_15")

    assert entry.wms_url == "https://geo.api.vlaanderen.be/OGW/wms"
    assert entry.wms_layer == "OGWRGB13_15VL"


def test_de_jaarlagen_staan_niet_op_de_inspire_dienst():
    """De mail wees 2016 en 2018 naar `oi/wms?layers=OI.OrthoimageCoverage.OMWRGB16VL`. Die laag
    bestaat niet: `oi/wms` heeft vier generieke dekkingen, de jaarlagen staan op OMW en OMZ."""
    for entry in c.entries("historisch"):
        assert "OI.OrthoimageCoverage" not in entry.wms_layer, entry.id
        assert "/oi/wms" not in entry.wms_url, entry.id


def test_de_archeologienotas_komen_van_mercator_en_niet_van_de_interne_dienst():
    """De GeoServer van onroerenderfgoed.be past perfect en mag toch niet: die zegt in zijn eigen
    GetCapabilities "Deze service is enkel bedoeld voor intern gebruik" en verwijst naar Mercator
    (gelezen 2026-10-04). Een publieke plugin mag geen interne dienst meeleveren, wat die ook
    bedient. Mercator publiek staat onder de Gratis Open Data Licentie Vlaanderen v1.2 en draagt
    dezelfde records, met dezelfde veldnamen."""
    entry = c.by_id("archeologienotas")

    assert entry.wms_url == MERCATOR + "/wms"
    assert entry.wms_layer == "am:am_archnts"
    assert entry.wfs_url == MERCATOR + "/wfs"
    assert entry.wfs_typename == "am:am_archnts"
    assert entry.fact_mode == "wfs"
    assert "onroerenderfgoed.be" not in entry.wms_url + entry.wfs_url
    for veld in ("naam", "type_naam", "datum_ind", "uri"):
        assert veld in entry.fact_fields, veld


def test_geen_enkele_kaart_hangt_aan_een_dienst_voor_intern_gebruik():
    """`geo.onroerenderfgoed.be` verklaart zichzelf intern, en `vioe_intern:` is niet publiek."""
    for entry in c.entries():
        assert "vioe_intern" not in entry.wms_layer, entry.id
        assert "geo.onroerenderfgoed.be" not in entry.wms_url, entry.id
        assert "geo.onroerenderfgoed.be" not in entry.wfs_url, entry.id


@pytest.mark.parametrize("map_id,laag", [
    ("geulen_luchtfotos", "geulenstelsel_naar_luchtfotos"),
    ("geulen_sinds_1570", "geulenstelsel_sinds_1570"),
    ("geulen_voor_1570", "geulenstelsel_voor_1570"),
])
def test_de_drie_geulenkaarten_staan_bij_de_geologie(map_id, laag):
    """Robin: "geulen bij geologie houden". Het zijn dijkdoorbraakgeulen langs de Schelde."""
    entry = c.by_id(map_id)

    assert entry.chapter == "geologie"
    assert entry.wms_layer == laag
    assert "dijken" in entry.wms_url
    assert entry.wfs_url == DOV_WFS_URL, "de globale DOV-WFS kent de dijken-typenames"


def test_de_waterlopen_worden_getekend_door_de_ene_dienst_en_bevraagd_bij_de_andere():
    """`VHAWaterlopen/wms` geeft nul lagen op 1.1.1 en op 1.3.0; het kaartbeeld komt van `hy/wms`.
    De WFS van VHAWaterlopen werkt wel, en daar staan de naam en de categorie."""
    entry = c.by_id("waterlopen")

    assert entry.wms_url == "https://geo.api.vlaanderen.be/hy/wms"
    assert entry.wms_layer == "HY.Network"
    assert entry.wfs_url == VHA_WFS
    assert entry.wfs_typename == "VHAWaterlopen:Wlas"
    for veld in ("NAAM", "LBLCATC"):
        assert veld in entry.fact_fields, veld


def test_de_peilmeetstations_zijn_een_kaart_en_geen_tabel():
    """De dienst heeft zes genummerde lagen; 3 is "meetpunten waterstand alle", 1 en 4 zijn
    debieten en 2 en 5 pluviografen. Een nummer naast de bedoeling levert een kaart van iets
    anders zonder dat er iets faalt.

    Geen feitentabel, want er is niets op te halen: GetFeatureInfo op deze ArcGIS-laag antwoordt
    niets, ook niet pal op een station (live 2026-10-04 op Destelbergen/Ledebeek, X 108252
    Y 194182, fijn en op 20 m per pixel). Het peil zelf is trouwens geen veld van de laag maar een
    tijdreeks achter een andere API. Het blad toont dus welke stations bij de zone staan."""
    entry = c.by_id("peilmeetstations")

    assert entry.wms_layer == "3"
    assert "meetpunten" in entry.wms_url
    assert entry.fact_mode is None


def test_de_watertoets_kent_ook_de_overstroming_vanuit_de_zee():
    """Stond in het oorspronkelijke ontwerp, zat niet in de catalogus."""
    entry = c.by_id("watertoets_zee")
    pluviaal = c.by_id("watertoets_pluviaal")

    assert "vanuit_de_zee" in entry.wms_url
    assert entry.wms_layer == pluviaal.wms_layer == "0"
    assert entry.fact_mode == pluviaal.fact_mode
    assert entry.gfi_format == pluviaal.gfi_format


def test_een_kaart_zonder_eigen_wfs_blijft_de_dov_wfs_vragen():
    """De negenentwintig kaarten van voor deze lijst mogen hier niets van merken."""
    for entry in c.entries():
        if entry.fact_mode == "wfs" and entry.id not in ("archeologienotas", "waterlopen"):
            assert entry.wfs_url == DOV_WFS_URL, entry.id


def test_niet_elk_orthofotojaar_staat_standaard_aan():
    """Robin vroeg de luchtfoto's "optioneel, met aanvinken". Eenentwintig jaren die allemaal
    standaard aanstaan maken het rapport in een keer ruim twintig bladen dikker, en v0.2.0 ging
    juist van 115 naar 62 bladen. Zes jaren gespreid over de decennia staan aan, de rest staat een
    vinkje ver."""
    aan = {e.id for e in c.entries() if e.on_by_default}
    ortho = {e.id for e in c.entries() if e.id.startswith("ortho_om") or e.id.startswith("ortho_ogw")}

    assert ortho - aan, "geen enkel orthofotojaar staat uit"
    assert ortho & aan == set(c.ORTHO_DEFAULT_IDS)
    assert len(c.ORTHO_DEFAULT_IDS) == 6


def test_alles_behalve_de_extra_orthofotojaren_staat_standaard_aan():
    """Een kaart uitzetten is een keuze; een kaart die stil uitstaat is een gat in het rapport."""
    uit = {e.id for e in c.entries() if not e.on_by_default}

    assert uit == set(c.ORTHO_WINTER_IDS + c.ORTHO_SUMMER_IDS) - set(c.ORTHO_DEFAULT_IDS)


def test_de_standaardkeuze_is_wat_de_dialoog_aanvinkt():
    assert c.default_map_ids() == [e.id for e in c.entries() if e.on_by_default]
