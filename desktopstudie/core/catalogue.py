"""Map catalogue: one entry per map. Adding a map = adding one entry here.
All URLs and layer names were verified live on 2026-09-15 (see design spec)."""
from __future__ import annotations

import types
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

DOV_WFS_URL = "https://www.dov.vlaanderen.be/geoserver/wfs"
DOV_WMS_URL = "https://www.dov.vlaanderen.be/geoserver/wms"
GEOCODER_URL = "https://geo.api.vlaanderen.be/geolocation/v4/Location"
VB_DOORPRIK_URL = "https://services.dov.vlaanderen.be/virtueleboringserver/base/virtueleprofielen/doorprik/{model}"
# Profile query: one column of layer THICKNESSES per distance step along a line; the record
# carries no absolute elevations, so callers stack from a known surface (see virtuele_boring).
VB_PROFILE_URL = (
    "https://services.dov.vlaanderen.be/virtueleboringserver/base/lagenmodel/{model}"
    "/profielbevraging/lagen"
)
WATERINFO_WMS_URL = (
    "https://inspirepub.waterinfo.be/arcgis/services/informatieplicht/"
    "overstromingsgevoelige_gebieden_{kind}/MapServer/WMSServer"
)
# Reserved for the QGIS shell (plan 2): it loads the DTM as a WCS coverage to fill StudyResult.relief.
DHMV_WCS_URL = "https://geo.api.vlaanderen.be/DHMV/wcs"
DHMV_WCS_COVERAGE = "DHMVII_DTM_1m"

DOV_LICENCE = "DOV, Vlaamse overheid - Modellicentie Gratis Hergebruik"
GEOPUNT_LICENCE = "Digitaal Vlaanderen - Modellicentie Gratis Hergebruik"

# Virtual-borehole model id -> the title the report prints for it. Here rather than in the
# service: it is presentation, the same kind of lookup as WATERTOETS_LABELS below, and the report
# needs it whether or not a study ever called the virtual-borehole endpoint.
MODEL_TITLES = {
    "g3dv3_F": "G3Dv3 - formaties",
    "g3dv3_L": "G3Dv3 - leden",
    "g3dv3_P": "G3Dv3 - periodes",
    "g3dv3_T": "G3Dv3 - tijdvakken",
    "hcovv1": "HCOV v1",
    "hcovv2_H": "HCOV v2 - hoofdeenheden",
    "hcovv2_S": "HCOV v2 - subeenheden",
    "hcovv2_B": "HCOV v2 - basiseenheden",
}

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
    # A named WMS style; "" asks the service for the layer default. Some maps are only correct
    # with a named style (gxg), and a style name is NOT a layer name - a GetMap on it fails.
    # It sits here rather than next to wms_layer because attribution has no default: a defaulted
    # field before it would break the dataclass, and every positional MapEntry(...) below it.
    wms_style: str = ""
    licence: str = GEOPUNT_LICENCE
    image_format: str = "image/png"
    opacity: float = 1.0
    legend: bool = False
    fact_mode: Optional[str] = None  # None | "wfs" | "gfi"
    wfs_typename: Optional[str] = None
    fact_fields: Tuple[str, ...] = ()
    value_labels: Dict[str, Dict[str, str]] = field(default_factory=dict, compare=False, hash=False)
    field_labels: Dict[str, str] = field(default_factory=dict, compare=False, hash=False)  # fact_field -> header
    enabled: bool = True
    note: str = ""
    # default map scale (1:scale) on the PDF page; the shell zooms out further only when the
    # zone does not fit
    scale: int = 5000

    def __post_init__(self) -> None:
        """Freeze the two label tables into read-only views, the inner ones included. The catalogue
        is module-level shared state: a caller that wrote into a label table would change the map
        for every later study in the same QGIS session. `object.__setattr__` is the only way into a
        frozen dataclass; both fields stay out of `__eq__`/`__hash__`, as they were."""
        object.__setattr__(self, "value_labels", types.MappingProxyType(
            {key: types.MappingProxyType(dict(value)) for key, value in self.value_labels.items()}))
        object.__setattr__(self, "field_labels", types.MappingProxyType(dict(self.field_labels)))


def _dov(map_id: str, title: str, layer: str, fields: Tuple[str, ...] = (), wfs: Optional[str] = None,
         legend: bool = True, opacity: float = 0.7, labels: Optional[Dict[str, Dict[str, str]]] = None,
         field_labels: Optional[Dict[str, str]] = None, *, scale: int, style: str = "") -> MapEntry:
    return MapEntry(id=map_id, chapter="geologie", title=title, wms_url=DOV_WMS_URL, wms_layer=layer,
                    attribution="Databank Ondergrond Vlaanderen (DOV)", wms_style=style, licence=DOV_LICENCE,
                    legend=legend, opacity=opacity, fact_mode="wfs" if wfs else None, wfs_typename=wfs,
                    fact_fields=fields, value_labels=labels or {}, field_labels=field_labels or {},
                    scale=scale)


def _hist(map_id: str, title: str, url: str, layer: str, fmt: str = "image/png", *, scale: int) -> MapEntry:
    return MapEntry(id=map_id, chapter="historisch", title=title, wms_url=url, wms_layer=layer,
                    attribution="Digitaal Vlaanderen / geopunt", image_format=fmt, scale=scale)


CATALOGUE: List[MapEntry] = [
    # --- ligging en topografie ---
    MapEntry("grb", "ligging", "GRB-basiskaart", "https://geo.api.vlaanderen.be/GRB-basiskaart/wms", "GRB_BSK",
             "Digitaal Vlaanderen - GRB-basiskaart", scale=2500),
    MapEntry("ortho", "ligging", "Orthofoto (meest recent)", "https://geo.api.vlaanderen.be/OMWRGBMRVL/wms", "Ortho",
             "Digitaal Vlaanderen - Orthofotomozaiek middenschalig winter, meest recent", image_format="image/jpeg",
             scale=2500),
    MapEntry("ngi_topo", "ligging", "Topografische kaart NGI (CartoWeb)", "https://cartoweb.wms.ngi.be/service", "topo",
             "Nationaal Geografisch Instituut - CartoWeb.be", licence="NGI open data", scale=10000),
    MapEntry("dhmv_hillshade", "ligging", "Digitaal Hoogtemodel Vlaanderen II - hillshade",
             "https://geo.api.vlaanderen.be/DHMV/wms", "DHMV_II_HILL_25cm", "Digitaal Vlaanderen - DHMV II",
             scale=5000),
    MapEntry("dhmv_dtm", "ligging", "Digitaal Hoogtemodel Vlaanderen II - DTM 1 m",
             "https://geo.api.vlaanderen.be/DHMV/wms", "DHMVII_DTM_1m", "Digitaal Vlaanderen - DHMV II", opacity=0.6,
             legend=True, scale=5000),
    # --- historische kaarten ---
    _hist("ferraris", "Ferrariskaart (1777)", "https://geo.api.vlaanderen.be/HISTCART/wms", "ferraris", scale=25000),
    _hist("abw", "Atlas der Buurtwegen (ca. 1840)", "https://geo.api.vlaanderen.be/HISTCART/wms", "abw", scale=5000),
    _hist("vandermaelen", "Topografische kaart Vandermaelen (1846-1854)", "https://geo.api.vlaanderen.be/HISTCART/wms",
          "vandermaelen", scale=20000),
    _hist("popp", "Popp-kaart (1842-1879)", "https://geo.api.vlaanderen.be/HISTCART/wms", "popp", scale=5000),
    _hist("ortho_1971", "Orthofoto 1971 (panchromatisch)", "https://geo.api.vlaanderen.be/OKZ/wms", "OKZPAN71VL",
          "image/jpeg", scale=5000),
    _hist("ortho_1979_90", "Orthofoto 1979-1990", "https://geo.api.vlaanderen.be/OKZ/wms", "OKZRGB79_90VL",
          "image/jpeg", scale=5000),
    _hist("ortho_2000_03", "Orthofoto 2000-2003", "https://geo.api.vlaanderen.be/OMW/wms", "OMWRGB00_03VL",
          "image/jpeg", scale=5000),
    MapEntry("ngi_hist", "historisch", "Historische topografische kaarten NGI (1873-1989)", "", "",
             "Nationaal Geografisch Instituut", enabled=False,
             note="Geen officiele open WMS beschikbaar (alleen het Cartesius-portaal). Vul wms_url en "
                  "wms_layer in en zet enabled=True zodra een service bestaat.", scale=25000),
    MapEntry("bommenkaart", "historisch", "Bommenkaart - conventionele en toxische explosieven", "", "",
             "Bommenkaart.be - Bom-Be BV", licence="Geen open data", enabled=False,
             note="Bommenkaart.be (Bom-Be BV) is geen open data en biedt geen WMS/WFS; raadpleeg de "
                  "kaart manueel en vermeld het risico op conventionele en toxische explosieven "
                  "(WOI/WOII) in de studie.", scale=10000),
    # --- geologie en bodem ---
    _dov("bodemkaart", "Bodemkaart van Vlaanderen", "bodemkaart:bodemtypes",
         ("Bodemtype", "Bodemserie", "Beknopte_omschrijving_bodemserie", "Textuurklasse", "Drainageklasse",
          "Gegeneraliseerde_legende", "Textuurklasse_code", "Drainageklasse_code"),
         wfs="bodemkaart:bodemtypes",
         field_labels={"Bodemtype": "Bodemtype", "Bodemserie": "Bodemserie",
                       "Beknopte_omschrijving_bodemserie": "Omschrijving", "Textuurklasse": "Textuur",
                       "Drainageklasse": "Drainage", "Gegeneraliseerde_legende": "Legende",
                       "Textuurklasse_code": "Textuurcode", "Drainageklasse_code": "Drainagecode"},
         scale=10000),
    _dov("quartair", "Quartairgeologische kaart 1/50 000 (samengesteld)", "quartair:quartair_samengesteld",
         ("profieltype", "legende"), wfs="quartair:quartair_samengesteld_50k_legende",
         field_labels={"profieltype": "Profieltype", "legende": "Legende (link)"}, scale=25000),
    _dov("quartair_200k", "Quartairgeologische kaart 1/200 000", "quartair:quartair_200k",
         ("type", "profiel"), wfs="quartair:quartair_200k",
         field_labels={"type": "Type", "profiel": "Profiel"}, scale=100000),
    _dov("quartair_dikte", "Dikte van het Quartair (isopachen)", "dov-pub:Quartair_Isopachen",
         ("dikte",), wfs="dov-pub:Quartair_Isopachen", legend=False, field_labels={"dikte": "Dikte (m)"},
         scale=50000),
    _dov("tertiair", "Tertiairgeologische kaart 1/50 000", "neo_paleo:tertiair_50k",
         ("code", "formatie", "lid", "beschrijving"), wfs="neo_paleo:tertiair_50k",
         field_labels={"code": "Code", "formatie": "Formatie", "lid": "Lid", "beschrijving": "Beschrijving"},
         scale=25000),
    _dov("hcov", "HCOV 0100 - Quartaire aquifersystemen (voorkomen)", "hcov:hcov_0100_vk",
         ("hcov_code", "hcov_naam"), wfs="hcov:hcov_0100_vk",
         field_labels={"hcov_code": "HCOV-code", "hcov_naam": "HCOV-naam"}, scale=25000),
    _dov("gw_kwetsbaarheid", "Grondwaterkwetsbaarheidskaart", "gw_bescherming:gwkwb_kwbschaal",
         ("kwetsbaarheidsschaal", "watervoerende_laag", "deklaag", "dikte_onverzadigde_zone", "indices"),
         wfs="gw_bescherming:gwkwb_kwbschaal",
         field_labels={"kwetsbaarheidsschaal": "Kwetsbaarheid", "watervoerende_laag": "Watervoerende laag",
                       "deklaag": "Deklaag", "dikte_onverzadigde_zone": "Onverzadigde zone", "indices": "Index"},
         scale=25000),
    # gxg:gxg is the STYLE, not the layer: the map is gxg:ghg_mmv_main drawn with it (live 2026-09-15).
    # GxG is a pair - the mean highest (GHG) and the mean lowest (GLG) level - and one page titled
    # "GxG" hides which of the two the reader has in front of him, so each level is its own entry.
    # gxg:glg_mmv_main with gxg:gxg verified live 2026-09-15 (GetMap -> HTTP 200, image/png).
    _dov("gxg", "Gemiddeld hoogste grondwaterstand (GHG)", "gxg:ghg_mmv_main", legend=True, scale=25000,
         style="gxg:gxg"),
    _dov("gxg_glg", "Gemiddeld laagste grondwaterstand (GLG)", "gxg:glg_mmv_main", legend=True, scale=25000,
         style="gxg:gxg"),
    MapEntry("watertoets_pluviaal", "geologie", "Watertoets - overstromingsgevoelige gebieden pluviaal",
             WATERINFO_WMS_URL.format(kind="pluviaal"), "0", "Vlaamse Milieumaatschappij - waterinfo.be",
             licence="VMM - geen beperkingen", opacity=0.7, legend=True, fact_mode="gfi",
             fact_fields=("gridcode",), value_labels={"gridcode": WATERTOETS_LABELS},
             field_labels={"gridcode": "Klasse"}, scale=10000),
    MapEntry("watertoets_fluviaal", "geologie", "Watertoets - overstromingsgevoelige gebieden fluviaal",
             WATERINFO_WMS_URL.format(kind="fluviaal"), "0", "Vlaamse Milieumaatschappij - waterinfo.be",
             licence="VMM - geen beperkingen", opacity=0.7, legend=True, fact_mode="gfi",
             fact_fields=("gridcode",), value_labels={"gridcode": WATERTOETS_LABELS},
             field_labels={"gridcode": "Klasse"}, scale=10000),
    _dov("erosie", "Potentiele bodemerosiekaart per perceel (2014)",
         "erosie:erosie_potentiele_bodemerosiekaart_per_perceel_2014",
         ("Erosieklasse_ALV", "Totale_erosie"), wfs="erosie:erosie_potentiele_bodemerosiekaart_per_perceel_2014",
         field_labels={"Erosieklasse_ALV": "Erosieklasse", "Totale_erosie": "Totale erosie"}, scale=10000),
    _dov("krimp_zwel", "Krimp-zwelgevoelige gronden (plastische gronden)", "plastische_gronden:krimp_zwel",
         ("Eenheid_G3Dv3_0", "hoofdlithologie", "code_G3Dv3_0"), wfs="plastische_gronden:IndexPlastisch",
         field_labels={"Eenheid_G3Dv3_0": "Eenheid", "hoofdlithologie": "Hoofdlithologie",
                       "code_G3Dv3_0": "Code"}, scale=25000),
    _dov("ovam", "OVAM - uitspraak bodemonderzoeken", "ovam:uitspraak_bodemonderzoeken",
         ("kadaster_id", "uitspraak", "risico_inrichting", "onder_voorbehoud"), wfs="ovam:uitspraak_bodemonderzoeken",
         field_labels={"kadaster_id": "Perceel", "uitspraak": "Uitspraak",
                       "risico_inrichting": "Risico-inrichting", "onder_voorbehoud": "Onder voorbehoud"},
         scale=5000),
    _dov("grondverschuiving_gevoeligheid", "Gevoeligheid voor grondverschuivingen",
         "grondverschuivingen:grndversch_gevoeligh", ("gevoelighd", "klasse"),
         wfs="grondverschuivingen:grndversch_gevoeligh",
         field_labels={"gevoelighd": "Gevoeligheid", "klasse": "Klasse"}, scale=25000),
    _dov("grondverschuiving_gekarteerd", "Gekarteerde grondverschuivingen",
         "grondverschuivingen:grndversch_gekarteerd", ("type", "naam", "gemeente", "helling", "rapport"),
         wfs="grondverschuivingen:grndversch_gekarteerd",
         field_labels={"type": "Type", "naam": "Naam", "gemeente": "Gemeente", "helling": "Helling",
                       "rapport": "Rapport"}, scale=10000),
    # The WMS layer is pfas:no_regret_huidig; "no_regret_zones" is one of its named STYLES, not a
    # layer of its own (live check 2026-09-15: GetMap on pfas:no_regret_zones -> LayerNotDefined).
    MapEntry("pfas_no_regret", "geologie", "PFAS - no-regretmaatregelen", DOV_WMS_URL,
             "pfas:no_regret_huidig", "OVAM / Vlaamse overheid via DOV", licence=DOV_LICENCE,
             opacity=0.7, legend=True, fact_mode="wfs", wfs_typename="pfas:no_regret_huidig",
             fact_fields=("pfasdossiernr", "gemeente", "straat", "nrm_status_zone", "zone_geldig_vanaf",
                          "no_regret_maatregelen"),
             field_labels={"pfasdossiernr": "PFAS-dossier", "gemeente": "Gemeente", "straat": "Straat",
                           "nrm_status_zone": "Status", "zone_geldig_vanaf": "Geldig vanaf",
                           "no_regret_maatregelen": "Maatregelen (link)"},
             scale=10000),
]


def entries(chapter: Optional[str] = None, enabled_only: bool = True) -> List[MapEntry]:
    return [e for e in CATALOGUE if (chapter is None or e.chapter == chapter) and (e.enabled or not enabled_only)]


def by_id(map_id: str) -> MapEntry:
    for e in CATALOGUE:
        if e.id == map_id:
            return e
    raise KeyError(map_id)
