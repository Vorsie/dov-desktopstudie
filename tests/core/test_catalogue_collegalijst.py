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
ERFGOED_WMS = "https://geo.onroerenderfgoed.be/geoserver/wms"
ERFGOED_WFS = "https://geo.onroerenderfgoed.be/geoserver/wfs"
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


def test_de_archeologienotas_worden_op_de_wfs_van_onroerend_erfgoed_gevraagd():
    """Eigen dienst, eigen WFS. Op het adres van DOV gevraagd antwoordt GeoServer leeg."""
    entry = c.by_id("archeologienotas")

    assert entry.wms_url == ERFGOED_WMS
    assert entry.wms_layer == "vioe_geoportaal:archeologienotas"
    assert entry.wfs_url == ERFGOED_WFS
    assert entry.wfs_typename == "vioe_geoportaal:archeologienotas"
    assert entry.fact_mode == "wfs"
    for veld in ("naam", "type_naam", "datum_ind", "uri"):
        assert veld in entry.fact_fields, veld


def test_de_interne_lagen_van_onroerend_erfgoed_blijven_buiten_de_catalogus():
    """`vioe_intern:` is niet publiek; een studie mag er niet van afhangen."""
    for entry in c.entries():
        assert "vioe_intern" not in entry.wms_layer, entry.id


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


def test_de_peilmeetstations_vragen_de_laag_met_de_waterstanden():
    """De dienst heeft zes genummerde lagen; 3 is "meetpunten waterstand alle", 1 en 4 zijn
    debieten en 2 en 5 pluviografen. Een nummer naast de bedoeling levert een kaart van iets
    anders zonder dat er iets faalt."""
    entry = c.by_id("peilmeetstations")

    assert entry.wms_layer == "3"
    assert "meetpunten" in entry.wms_url
    assert entry.fact_mode == "gfi"


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
