"""Map catalogue: one entry per map. Adding a map = adding one entry here.
All URLs and layer names were verified live on 2026-09-15 (see design spec)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

DOV_WFS_URL = "https://www.dov.vlaanderen.be/geoserver/wfs"
DOV_WMS_URL = "https://www.dov.vlaanderen.be/geoserver/wms"
GEOCODER_URL = "https://geo.api.vlaanderen.be/geolocation/v4/Location"
VB_DOORPRIK_URL = "https://services.dov.vlaanderen.be/virtueleboringserver/base/virtueleprofielen/doorprik/{model}"
WATERINFO_WMS_URL = (
    "https://inspirepub.waterinfo.be/arcgis/services/informatieplicht/"
    "overstromingsgevoelige_gebieden_{kind}/MapServer/WMSServer"
)
DHMV_WCS_URL = "https://geo.api.vlaanderen.be/DHMV/wcs"
DHMV_WCS_COVERAGE = "DHMVII_DTM_1m"

DOV_LICENCE = "DOV, Vlaamse overheid - Modellicentie Gratis Hergebruik"
GEOPUNT_LICENCE = "Digitaal Vlaanderen - Modellicentie Gratis Hergebruik"

WATERTOETS_LABELS = {
    "0": "A - Geen overstroming gemodelleerd",
    "1": "B - Kleine kans op overstromingen onder klimaatverandering",
    "2": "C - Kleine kans op overstromingen",
    "3": "D - Middelgrote kans op overstromingen",
}


@dataclass(frozen=True)
class MapEntry:
    id: str
    chapter: str  # "ligging" | "historisch" | "geologie"
    title: str
    wms_url: str
    wms_layer: str
    attribution: str
    licence: str = GEOPUNT_LICENCE
    image_format: str = "image/png"
    opacity: float = 1.0
    legend: bool = False
    fact_mode: Optional[str] = None  # None | "wfs" | "gfi"
    wfs_typename: Optional[str] = None
    fact_fields: Tuple[str, ...] = ()
    value_labels: Dict[str, Dict[str, str]] = field(default_factory=dict, compare=False, hash=False)
    enabled: bool = True
    note: str = ""


def _dov(map_id: str, title: str, layer: str, fields: Tuple[str, ...] = (), wfs: Optional[str] = None,
         legend: bool = True, opacity: float = 0.7, labels: Optional[Dict[str, Dict[str, str]]] = None) -> MapEntry:
    return MapEntry(id=map_id, chapter="geologie", title=title, wms_url=DOV_WMS_URL, wms_layer=layer,
                    attribution="Databank Ondergrond Vlaanderen (DOV)", licence=DOV_LICENCE, legend=legend,
                    opacity=opacity, fact_mode="wfs" if wfs else None, wfs_typename=wfs, fact_fields=fields,
                    value_labels=labels or {})


def _hist(map_id: str, title: str, url: str, layer: str, fmt: str = "image/png") -> MapEntry:
    return MapEntry(id=map_id, chapter="historisch", title=title, wms_url=url, wms_layer=layer,
                    attribution="Digitaal Vlaanderen / geopunt", image_format=fmt)


CATALOGUE: List[MapEntry] = [
    # --- ligging en topografie ---
    MapEntry("grb", "ligging", "GRB-basiskaart", "https://geo.api.vlaanderen.be/GRB-basiskaart/wms", "GRB_BSK",
             "Digitaal Vlaanderen - GRB-basiskaart"),
    MapEntry("ortho", "ligging", "Orthofoto (meest recent)", "https://geo.api.vlaanderen.be/OMWRGBMRVL/wms", "Ortho",
             "Digitaal Vlaanderen - Orthofotomozaiek middenschalig winter, meest recent", image_format="image/jpeg"),
    MapEntry("ngi_topo", "ligging", "Topografische kaart NGI (CartoWeb)", "https://cartoweb.wms.ngi.be/service", "topo",
             "Nationaal Geografisch Instituut - CartoWeb.be", licence="NGI open data"),
    MapEntry("dhmv_hillshade", "ligging", "Digitaal Hoogtemodel Vlaanderen II - hillshade",
             "https://geo.api.vlaanderen.be/DHMV/wms", "DHMV_II_HILL_25cm", "Digitaal Vlaanderen - DHMV II"),
    MapEntry("dhmv_dtm", "ligging", "Digitaal Hoogtemodel Vlaanderen II - DTM 1 m",
             "https://geo.api.vlaanderen.be/DHMV/wms", "DHMVII_DTM_1m", "Digitaal Vlaanderen - DHMV II", opacity=0.6,
             legend=True),
    # --- historische kaarten ---
    _hist("ferraris", "Ferrariskaart (1777)", "https://geo.api.vlaanderen.be/HISTCART/wms", "ferraris"),
    _hist("abw", "Atlas der Buurtwegen (ca. 1840)", "https://geo.api.vlaanderen.be/HISTCART/wms", "abw"),
    _hist("vandermaelen", "Topografische kaart Vandermaelen (1846-1854)", "https://geo.api.vlaanderen.be/HISTCART/wms",
          "vandermaelen"),
    _hist("popp", "Popp-kaart (1842-1879)", "https://geo.api.vlaanderen.be/HISTCART/wms", "popp"),
    _hist("ortho_1971", "Orthofoto 1971 (panchromatisch)", "https://geo.api.vlaanderen.be/OKZ/wms", "OKZPAN71VL",
          "image/jpeg"),
    _hist("ortho_1979_90", "Orthofoto 1979-1990", "https://geo.api.vlaanderen.be/OKZ/wms", "OKZRGB79_90VL",
          "image/jpeg"),
    _hist("ortho_2000_03", "Orthofoto 2000-2003", "https://geo.api.vlaanderen.be/OMW/wms", "OMWRGB00_03VL",
          "image/jpeg"),
    MapEntry("ngi_hist", "historisch", "Historische topografische kaarten NGI (1873-1989)", "", "",
             "Nationaal Geografisch Instituut", enabled=False,
             note="Geen officiele open WMS beschikbaar (alleen het Cartesius-portaal). Vul wms_url en "
                  "wms_layer in en zet enabled=True zodra een service bestaat."),
    # --- geologie en bodem ---
    _dov("bodemkaart", "Bodemkaart van Vlaanderen", "bodemkaart:bodemtypes",
         ("Bodemtype", "Bodemserie", "Beknopte_omschrijving_bodemserie", "Textuurklasse", "Drainageklasse",
          "Gegeneraliseerde_legende"),
         wfs="bodemkaart:bodemtypes"),
    _dov("quartair", "Quartairgeologische kaart 1/50 000 (samengesteld)", "quartair:quartair_samengesteld",
         ("profieltype", "legende"), wfs="quartair:quartair_samengesteld_50k_legende"),
    _dov("quartair_200k", "Quartairgeologische kaart 1/200 000", "quartair:quartair_200k",
         ("type", "profiel"), wfs="quartair:quartair_200k"),
    _dov("quartair_dikte", "Dikte van het Quartair (isopachen)", "dov-pub:Quartair_Isopachen",
         ("dikte",), wfs="dov-pub:Quartair_Isopachen", legend=False),
    _dov("tertiair", "Tertiairgeologische kaart 1/50 000", "neo_paleo:tertiair_50k",
         ("code", "formatie", "lid", "beschrijving"), wfs="neo_paleo:tertiair_50k"),
    _dov("hcov", "HCOV 0100 - Quartaire aquifersystemen (voorkomen)", "hcov:hcov_0100_vk",
         ("hcov_code", "hcov_naam"), wfs="hcov:hcov_0100_vk"),
    _dov("gw_kwetsbaarheid", "Grondwaterkwetsbaarheidskaart", "gw_bescherming:gwkwb_kwbschaal",
         ("kwetsbaarheidsschaal", "watervoerende_laag", "deklaag", "dikte_onverzadigde_zone", "indices"),
         wfs="gw_bescherming:gwkwb_kwbschaal"),
    _dov("gxg", "Grondwaterstanden GxG (GHG/GLG)", "gxg:gxg", legend=True),
    MapEntry("watertoets_pluviaal", "geologie", "Watertoets - overstromingsgevoelige gebieden pluviaal",
             WATERINFO_WMS_URL.format(kind="pluviaal"), "0", "Vlaamse Milieumaatschappij - waterinfo.be",
             licence="VMM - geen beperkingen", opacity=0.7, legend=True, fact_mode="gfi",
             fact_fields=("gridcode",), value_labels={"gridcode": WATERTOETS_LABELS}),
    MapEntry("watertoets_fluviaal", "geologie", "Watertoets - overstromingsgevoelige gebieden fluviaal",
             WATERINFO_WMS_URL.format(kind="fluviaal"), "0", "Vlaamse Milieumaatschappij - waterinfo.be",
             licence="VMM - geen beperkingen", opacity=0.7, legend=True, fact_mode="gfi",
             fact_fields=("gridcode",), value_labels={"gridcode": WATERTOETS_LABELS}),
    _dov("erosie", "Potentiele bodemerosiekaart per perceel (2014)",
         "erosie:erosie_potentiele_bodemerosiekaart_per_perceel_2014",
         ("Erosieklasse_ALV", "Totale_erosie"), wfs="erosie:erosie_potentiele_bodemerosiekaart_per_perceel_2014"),
    _dov("krimp_zwel", "Krimp-zwelgevoelige gronden (plastische gronden)", "plastische_gronden:krimp_zwel",
         ("Eenheid_G3Dv3_0", "hoofdlithologie", "code_G3Dv3_0"), wfs="plastische_gronden:IndexPlastisch"),
    _dov("ovam", "OVAM - uitspraak bodemonderzoeken", "ovam:uitspraak_bodemonderzoeken",
         ("kadaster_id", "uitspraak", "risico_inrichting", "onder_voorbehoud"), wfs="ovam:uitspraak_bodemonderzoeken"),
]


def entries(chapter: Optional[str] = None, enabled_only: bool = True) -> List[MapEntry]:
    return [e for e in CATALOGUE if (chapter is None or e.chapter == chapter) and (e.enabled or not enabled_only)]


def by_id(map_id: str) -> MapEntry:
    for e in CATALOGUE:
        if e.id == map_id:
            return e
    raise KeyError(map_id)
