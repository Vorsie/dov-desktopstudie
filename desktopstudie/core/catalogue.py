"""Map catalogue: one entry per map. Adding a map = adding one entry here.
All URLs and layer names were verified live on 2026-09-15 (see design spec); the DOV maps moved
to their workspace services on 2026-09-16, verified live against the global service the same day."""
from __future__ import annotations

import types
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple

DOV_WFS_URL = "https://www.dov.vlaanderen.be/geoserver/wfs"
DOV_WMS_URL = "https://www.dov.vlaanderen.be/geoserver/wms"
# The DOV maps are asked at the service of their own GeoServer workspace, not at the global one
# above. A WMS layer costs a GetCapabilities, and the global service answers with the whole of
# DOV: 1,1 MB that QGIS parses for 2,6 s per map, fifteen times a study. A workspace service
# answers with a few kB (0,03 s a map) and serves identical GetMap and GetLegendGraphic bytes -
# live 2026-09-16 for all fifteen. On it a layer goes by its own name, without the prefix.
DOV_WORKSPACE_WMS_URL = "https://www.dov.vlaanderen.be/geoserver/{workspace}/wms"
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
# What the two ends of the DTM's colour ramp mean, in mTAW. Read off the service's own
# GetLegendGraphic and not out of a document: it answers with a 102 x 68 px image holding the title
# "Hoogte (m TAW)", a vertical gradient of 16 x 48 px and the range "300 - -50" printed beside it
# (live 2026-09-17). The report prints that gradient as a horizontal strip under the map and needs
# the two ends as numbers; the colours themselves stay the service's, never invented ones.
DHMV_RAMP_MTAW = (-50.0, 300.0)

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

# --- reading guides ------------------------------------------------------------------------------
# One short text per map whose codes mean nothing on sight ("OB", "22026", "GeVl", "Dc"). They are
# written for a reader who is not a geologist: every term is explained where it is used, and the
# maps whose full legend runs to hundreds of classes end with the DOV page that holds it. Three to
# five sentences each - a leeswijzer nobody reads is worth as much as no leeswijzer.
#
# They live here, next to the fields they explain, rather than in the report: a map is one
# catalogue entry, guide included.
GUIDE_BODEMKAART = (
    "De bodemcode leest u letter voor letter. "
    "De eerste letter is de textuur van de bovengrond: Z zand, S lemig zand, P licht zandleem, "
    "L zandleem, A leem, E klei, U zware klei, V veen. "
    "De tweede letter is de natuurlijke drainage, van a (zeer droog) over d (matig nat) tot "
    "i (zeer nat); de derde letter is de profielontwikkeling, dus hoever de bodem zich al in lagen "
    "heeft gesorteerd (a, b, c, ...). "
    "Codes die met O beginnen zijn kunstmatige gronden - opgehoogd, vergraven of bebouwd - zonder "
    "natuurlijk profiel. "
    "Volledige legende: https://www.dov.vlaanderen.be/page/digitale-bodemkaart-van-het-vlaams-gewest")
# The composite 1/50 000 map numbers its profile types (22026, 22010); the cijfer-plus-letter code
# (3a, 1) belongs to the 1/200 000 map below. Checked against the recorded WFS answers of both.
GUIDE_QUARTAIR = (
    "Het profieltype is een nummer; elk nummer hoort bij een vaste opeenvolging van Quartaire "
    "afzettingen (zand, leem, klei of veen) boven de Tertiaire ondergrond. "
    "Achter deze tabel staat per profieltype de tekening van DOV: eerst het type zelf met zijn "
    "kleur, lettercode en omschrijving, daarna de eenhedentabel van het kaartblad, die van boven "
    "naar onder loopt - van de jongste laag aan het maaiveld tot de oudste. "
    "Het Quartair is de jongste geologische periode, alles wat de laatste 2,6 miljoen jaar is "
    "afgezet, en is meestal het pakket waarin gefundeerd wordt. "
    "Volledige legende: https://www.dov.vlaanderen.be/page/quartairgeologische-kaart-150000")
GUIDE_QUARTAIR_200K = (
    "De code van deze overzichtskaart bestaat uit een cijfer en soms een letter. "
    "Het cijfer benoemt de Pleistocene sequentie: de opeenvolging van oudere ijstijdafzettingen "
    "onder het maaiveld. "
    "De letter benoemt de Holocene toplaag, de jongste afzetting aan de oppervlakte (a staat voor "
    "rivierafzettingen); staat er geen letter, dan ligt de Pleistocene sequentie zelf aan de "
    "oppervlakte. "
    "Deze kaart is een overzicht op 1/200 000; voor de zone zelf is de kaart 1/50 000 hierboven "
    "nauwkeuriger. "
    "Volledige legende: https://www.dov.vlaanderen.be/page/quartairgeologische-kaart-1200000")
GUIDE_TERTIAIR = (
    "De code noemt de Tertiaire eenheid onder het Quartair: de eerste twee letters staan voor de "
    "formatie, de twee daarna voor het lid, een onderdeel van die formatie. "
    "GeVl is dus het Lid van Vlierzele in de Formatie van Gentbrugge. "
    "De kolom Beschrijving zegt waaruit de eenheid bestaat - korrelgrootte, kleur en bijmenging - "
    "en dat is wat voor een fundering telt. "
    "De kaart toont de eenheid aan de top van het Tertiair, niet wat daaronder ligt. "
    "Volledige legende: https://www.dov.vlaanderen.be/page/tertiairgeologische-kaart-150000")
GUIDE_DHMV_DTM = (
    "Het digitaal hoogtemodel geeft de hoogte van het maaiveld in meter TAW, de Belgische "
    "hoogtereferentie waarvan het nulpunt ongeveer op het gemiddelde laagwater in Oostende ligt. "
    "De kleurschaal op de kaart loopt over de hele hoogte van Vlaanderen, van ongeveer -50 tot "
    "300 m TAW. "
    "Binnen een bouwzone scheelt dat zelden meer dan enkele meters, dus verschilt de kleur er "
    "nauwelijks. "
    "Het gemeten minimum, maximum en gemiddelde over de zone zelf staan in de tabel Kerngegevens "
    "ligging.")
GUIDE_GW_KWETSBAARHEID = (
    "De index van twee of drie tekens vat de drie kolommen ernaast samen. "
    "De hoofdletter staat voor de watervoerende laag, de kleine letter voor de deklaag erboven en "
    "het cijfer voor de dikte van de onverzadigde zone (de grond boven de grondwatertafel). "
    "Hoe dunner en zandiger de deklaag, hoe sneller een verontreiniging het grondwater bereikt en "
    "hoe kwetsbaarder de zone. "
    "De kolom Kwetsbaarheid geeft het eindoordeel voluit, van zeer kwetsbaar tot weinig "
    "kwetsbaar.")
GUIDE_WATERTOETS = (
    "De watertoetskaart deelt het gebied in vier klassen in. "
    "A is geen overstroming gemodelleerd, B een kleine kans onder klimaatverandering, C een kleine "
    "kans en D een middelgrote kans op overstroming. "
    "De tabel geeft de klasse van de bevraagde punten binnen de zone, met de ruwe code van de "
    "dienst tussen rechte haken. "
    "Pluviaal gaat over water dat bij hevige regen blijft staan, fluviaal over water uit een "
    "waterloop die buiten haar oevers treedt.")
GUIDE_EROSIE = (
    "De kaart geeft per landbouwperceel hoeveel bodem er in theorie kan wegspoelen of wegschuiven. "
    "Totale erosie is het eindoordeel voluit, van verwaarloosbaar tot zeer hoog. "
    "Erosieklasse is de klasse die het perceel van het Departement Landbouw en Visserij kreeg; een "
    "streepje betekent dat het perceel geen klasse heeft. "
    "De kaart bestaat alleen voor landbouwpercelen, dus een zone zonder percelen levert geen "
    "rijen op.")
GUIDE_KRIMP_ZWEL = (
    "Deze kaart toont waar plastische gronden voorkomen: klei- en silthoudende lagen die uitzetten "
    "als ze nat worden en krimpen als ze uitdrogen. "
    "Die beweging kan funderingen en verhardingen doen scheuren, vooral bij ondiep funderen. "
    "De kolom Hoofdlithologie zegt waaruit de laag hoofdzakelijk bestaat: klei of silt is "
    "gevoelig, grind en zand niet. "
    "Eenheid en code benoemen de geologische laag uit het model G3Dv3 waarop de beoordeling "
    "slaat.")
GUIDE_PFAS = (
    "Deze kaart toont de zones waarvoor de Vlaamse overheid no-regretmaatregelen rond "
    "PFAS-verontreiniging heeft afgekondigd. "
    "Die maatregelen gaan over het gebruik van bodem, grondwater en tuingroenten; ze zeggen niets "
    "over gemeten gehaltes op deze locatie. "
    "Status zegt of de zone locatiespecifiek is vastgesteld of voorlopig geldt. "
    "De kolom Maatregelen (link) verwijst naar de maatregelen zelf; grondverzet binnen zo'n zone "
    "volgt een eigen procedure.")
GUIDE_GRONDVERSCHUIVING = (
    "Deze kaart schat hoe gevoelig een helling is voor grondverschuiving: het traag afglijden van "
    "een pakket grond over een diepere, nattere laag. "
    "Klasse 1 is de laagste gevoeligheid; hogere klassen betekenen meer gevoeligheid, en de kolom "
    "Gevoeligheid zegt hetzelfde voluit. "
    "De schatting komt uit hellingsgraad en ondergrond, niet uit een waarneming ter plaatse. "
    "De kaart van de gekarteerde grondverschuivingen toont wel waar er een is vastgesteld.")
GUIDE_GRONDVERSCHUIVING_GEKARTEERD = (
    "Deze kaart toont grondverschuivingen die op het terrein zijn vastgesteld en ingetekend. "
    "Type zegt om welke soort het gaat, bijvoorbeeld een grote verschuiving met een diep "
    "schuifvlak - het vlak waarover het grondpakket is afgegleden. "
    "Helling is de terreinhelling ter plaatse. "
    "De kolom Rapport verwijst naar de steekkaart van DOV met de beschrijving van die "
    "verschuiving.")
GUIDE_HCOV = (
    "HCOV is de Hydrogeologische Codering van de Ondergrond van Vlaanderen: een indeling van de "
    "ondergrond in watervoerende en slecht doorlatende lagen. "
    "Code 0100 staat voor de Quartaire aquifersystemen, de jonge zand- en grindlagen vlak onder "
    "het maaiveld waarin het ondiepe grondwater zit. "
    "Deze kaart toont alleen waar die eenheid voorkomt, niet hoe dik ze is of hoeveel water ze "
    "geeft. "
    "De virtuele boring geeft de HCOV-lagen op diepte voor het representatieve punt van de zone.")


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
    # Passed to GetLegendGraphic when the shell fetches the legend as an image. The default suits
    # GeoServer (DOV, geopunt): without it a map with many classes answers with one endless column
    # that no page can hold. ArcGIS services ignore the parameter, so it is harmless there.
    # Two columns of 9 pt rather than four of 7: four columns fit a screen, not a reader - the
    # class names run into each other and the swatch is the size of a full stop. `forceLabels:on`
    # makes GeoServer print the class name even where it would leave it out (a single-class layer),
    # which is the difference between a coloured square and a legend. The image gets taller this
    # way, and a legend taller than a sheet is cut into page-high strips by the shell anyway.
    legend_options: str = "columns:2;columnheight:1100;fontSize:9;forceLabels:on"
    fact_mode: Optional[str] = None  # None | "wfs" | "gfi"
    wfs_typename: Optional[str] = None
    fact_fields: Tuple[str, ...] = ()
    value_labels: Dict[str, Dict[str, str]] = field(default_factory=dict, compare=False, hash=False)
    field_labels: Dict[str, str] = field(default_factory=dict, compare=False, hash=False)  # fact_field -> header
    enabled: bool = True
    note: str = ""
    # Three to five sentences telling the reader how to read this map's codes, printed as a
    # "Leeswijzer" page behind the map. Empty for a map that needs none (a historical photo).
    reading_guide: str = ""
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


def dov_wms(layer: str) -> Tuple[str, str]:
    """(service URL, layer name) for a DOV layer named the DOV way, `workspace:name`.

    The prefixed name is how DOV lists its layers and how the WFS wants its typenames; the WMS of
    the workspace itself knows the layer by the bare name (see DOV_WORKSPACE_WMS_URL).
    """
    workspace, _, name = layer.partition(":")
    return DOV_WORKSPACE_WMS_URL.format(workspace=workspace), name


def _dov(map_id: str, title: str, layer: str, fields: Tuple[str, ...] = (), wfs: Optional[str] = None,
         legend: bool = True, opacity: float = 0.7, labels: Optional[Dict[str, Dict[str, str]]] = None,
         field_labels: Optional[Dict[str, str]] = None, *, scale: int, style: str = "",
         guide: str = "") -> MapEntry:
    url, name = dov_wms(layer)
    return MapEntry(id=map_id, chapter="geologie", title=title, wms_url=url, wms_layer=name,
                    attribution="Databank Ondergrond Vlaanderen (DOV)", wms_style=style, licence=DOV_LICENCE,
                    legend=legend, opacity=opacity, fact_mode="wfs" if wfs else None, wfs_typename=wfs,
                    fact_fields=fields, value_labels=labels or {}, field_labels=field_labels or {},
                    reading_guide=guide, scale=scale)


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
    # legend=False: GetLegendGraphic answers with a colour ramp of 27 x 18 mm carrying two numbers
    # (300 to -50), and a whole sheet for a strip that size is a sheet the reader turns past. What
    # the colours mean - height in mTAW - is a sentence, and it stands in the reading guide below.
    MapEntry("dhmv_dtm", "ligging", "Digitaal Hoogtemodel Vlaanderen II - DTM 1 m",
             "https://geo.api.vlaanderen.be/DHMV/wms", "DHMVII_DTM_1m", "Digitaal Vlaanderen - DHMV II", opacity=0.6,
             legend=False, reading_guide=GUIDE_DHMV_DTM, scale=5000),
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
    # legend=False on purpose: the soil legend lists every soil series in Flanders, which fills
    # pages nobody reads. The fact table below the map names the types inside the zone instead.
    _dov("bodemkaart", "Bodemkaart van Vlaanderen", "bodemkaart:bodemtypes",
         ("Bodemtype", "Bodemserie", "Beknopte_omschrijving_bodemserie", "Textuurklasse", "Drainageklasse",
          "Gegeneraliseerde_legende", "Textuurklasse_code", "Drainageklasse_code"),
         wfs="bodemkaart:bodemtypes", legend=False,
         field_labels={"Bodemtype": "Bodemtype", "Bodemserie": "Bodemserie",
                       "Beknopte_omschrijving_bodemserie": "Omschrijving", "Textuurklasse": "Textuur",
                       "Drainageklasse": "Drainage", "Gegeneraliseerde_legende": "Legende",
                       "Textuurklasse_code": "Textuurcode", "Drainageklasse_code": "Drainagecode"},
         guide=GUIDE_BODEMKAART, scale=10000),
    # legend=False, same reason as hcov below: GetLegendGraphic answers with a single 20x20 swatch
    # that names no class at all, and a page holding one coloured square helps nobody. The fact
    # table lists the profile types inside the zone instead.
    _dov("quartair", "Quartairgeologische kaart 1/50 000 (samengesteld)", "quartair:quartair_samengesteld",
         ("profieltype", "legende"), wfs="quartair:quartair_samengesteld_50k_legende", legend=False,
         field_labels={"profieltype": "Profieltype", "legende": "Legende (link)"},
         guide=GUIDE_QUARTAIR, scale=25000),
    _dov("quartair_200k", "Quartairgeologische kaart 1/200 000", "quartair:quartair_200k",
         ("type", "profiel"), wfs="quartair:quartair_200k",
         field_labels={"type": "Type", "profiel": "Profiel"}, guide=GUIDE_QUARTAIR_200K,
         scale=100000),
    _dov("quartair_dikte", "Dikte van het Quartair (isopachen)", "dov-pub:Quartair_Isopachen",
         ("dikte",), wfs="dov-pub:Quartair_Isopachen", legend=False, field_labels={"dikte": "Dikte (m)"},
         scale=50000),
    _dov("tertiair", "Tertiairgeologische kaart 1/50 000", "neo_paleo:tertiair_50k",
         ("code", "formatie", "lid", "beschrijving"), wfs="neo_paleo:tertiair_50k",
         field_labels={"code": "Code", "formatie": "Formatie", "lid": "Lid", "beschrijving": "Beschrijving"},
         guide=GUIDE_TERTIAIR, scale=25000),
    # legend=False: the legend of this single-class layer is a 20x20 swatch without a label - a
    # whole sheet for one coloured square. The HCOV code and name of the zone are in the fact table.
    _dov("hcov", "HCOV 0100 - Quartaire aquifersystemen (voorkomen)", "hcov:hcov_0100_vk",
         ("hcov_code", "hcov_naam"), wfs="hcov:hcov_0100_vk", legend=False,
         field_labels={"hcov_code": "HCOV-code", "hcov_naam": "HCOV-naam"}, guide=GUIDE_HCOV,
         scale=25000),
    _dov("gw_kwetsbaarheid", "Grondwaterkwetsbaarheidskaart", "gw_bescherming:gwkwb_kwbschaal",
         ("kwetsbaarheidsschaal", "watervoerende_laag", "deklaag", "dikte_onverzadigde_zone", "indices"),
         wfs="gw_bescherming:gwkwb_kwbschaal",
         field_labels={"kwetsbaarheidsschaal": "Kwetsbaarheid", "watervoerende_laag": "Watervoerende laag",
                       "deklaag": "Deklaag", "dikte_onverzadigde_zone": "Onverzadigde zone", "indices": "Index"},
         guide=GUIDE_GW_KWETSBAARHEID, scale=25000),
    # gxg:gxg is the STYLE, not the layer: the map is gxg:ghg_mmv_main drawn with it (live 2026-09-15).
    # GxG is a pair - the mean highest (GHG) and the mean lowest (GLG) level - and one page titled
    # "GxG" hides which of the two the reader has in front of him, so each level is its own entry.
    # gxg:glg_mmv_main with gxg:gxg verified live 2026-09-15 (GetMap -> HTTP 200, image/png).
    _dov("gxg_ghg", "Gemiddeld hoogste grondwaterstand (GHG)", "gxg:ghg_mmv_main", legend=True, scale=25000,
         style="gxg:gxg"),
    _dov("gxg_glg", "Gemiddeld laagste grondwaterstand (GLG)", "gxg:glg_mmv_main", legend=True, scale=25000,
         style="gxg:gxg"),
    MapEntry("watertoets_pluviaal", "geologie", "Watertoets - overstromingsgevoelige gebieden pluviaal",
             WATERINFO_WMS_URL.format(kind="pluviaal"), "0", "Vlaamse Milieumaatschappij - waterinfo.be",
             licence="VMM - geen beperkingen", opacity=0.7, legend=True, fact_mode="gfi",
             fact_fields=("gridcode",), value_labels={"gridcode": WATERTOETS_LABELS},
             field_labels={"gridcode": "Klasse"}, reading_guide=GUIDE_WATERTOETS, scale=10000),
    MapEntry("watertoets_fluviaal", "geologie", "Watertoets - overstromingsgevoelige gebieden fluviaal",
             WATERINFO_WMS_URL.format(kind="fluviaal"), "0", "Vlaamse Milieumaatschappij - waterinfo.be",
             licence="VMM - geen beperkingen", opacity=0.7, legend=True, fact_mode="gfi",
             fact_fields=("gridcode",), value_labels={"gridcode": WATERTOETS_LABELS},
             field_labels={"gridcode": "Klasse"}, reading_guide=GUIDE_WATERTOETS, scale=10000),
    _dov("erosie", "Potentiele bodemerosiekaart per perceel (2014)",
         "erosie:erosie_potentiele_bodemerosiekaart_per_perceel_2014",
         ("Erosieklasse_ALV", "Totale_erosie"), wfs="erosie:erosie_potentiele_bodemerosiekaart_per_perceel_2014",
         field_labels={"Erosieklasse_ALV": "Erosieklasse", "Totale_erosie": "Totale erosie"},
         guide=GUIDE_EROSIE, scale=10000),
    _dov("krimp_zwel", "Krimp-zwelgevoelige gronden (plastische gronden)", "plastische_gronden:krimp_zwel",
         ("Eenheid_G3Dv3_0", "hoofdlithologie", "code_G3Dv3_0"), wfs="plastische_gronden:IndexPlastisch",
         field_labels={"Eenheid_G3Dv3_0": "Eenheid", "hoofdlithologie": "Hoofdlithologie",
                       "code_G3Dv3_0": "Code"}, guide=GUIDE_KRIMP_ZWEL, scale=25000),
    _dov("ovam", "OVAM - uitspraak bodemonderzoeken", "ovam:uitspraak_bodemonderzoeken",
         ("kadaster_id", "uitspraak", "risico_inrichting", "onder_voorbehoud"), wfs="ovam:uitspraak_bodemonderzoeken",
         field_labels={"kadaster_id": "Perceel", "uitspraak": "Uitspraak",
                       "risico_inrichting": "Risico-inrichting", "onder_voorbehoud": "Onder voorbehoud"},
         scale=5000),
    _dov("grondverschuiving_gevoeligheid", "Gevoeligheid voor grondverschuivingen",
         "grondverschuivingen:grndversch_gevoeligh", ("gevoelighd", "klasse"),
         wfs="grondverschuivingen:grndversch_gevoeligh",
         field_labels={"gevoelighd": "Gevoeligheid", "klasse": "Klasse"},
         guide=GUIDE_GRONDVERSCHUIVING, scale=25000),
    _dov("grondverschuiving_gekarteerd", "Gekarteerde grondverschuivingen",
         "grondverschuivingen:grndversch_gekarteerd", ("type", "naam", "gemeente", "helling", "rapport"),
         wfs="grondverschuivingen:grndversch_gekarteerd",
         field_labels={"type": "Type", "naam": "Naam", "gemeente": "Gemeente", "helling": "Helling",
                       "rapport": "Rapport"}, guide=GUIDE_GRONDVERSCHUIVING_GEKARTEERD, scale=10000),
    # The WMS layer is pfas:no_regret_huidig; "no_regret_zones" is one of its named STYLES, not a
    # layer of its own (live check 2026-09-15: GetMap on pfas:no_regret_zones -> LayerNotDefined).
    MapEntry("pfas_no_regret", "geologie", "PFAS - no-regretmaatregelen", *dov_wms("pfas:no_regret_huidig"),
             "OVAM / Vlaamse overheid via DOV", licence=DOV_LICENCE,
             opacity=0.7, legend=True, fact_mode="wfs", wfs_typename="pfas:no_regret_huidig",
             fact_fields=("pfasdossiernr", "gemeente", "straat", "nrm_status_zone", "zone_geldig_vanaf",
                          "no_regret_maatregelen"),
             field_labels={"pfasdossiernr": "PFAS-dossier", "gemeente": "Gemeente", "straat": "Straat",
                           "nrm_status_zone": "Status", "zone_geldig_vanaf": "Geldig vanaf",
                           # "(bron)", not "(link)": the report prints the URL folded, and the
                           # fragment that points at the measure itself does not survive that.
                           "no_regret_maatregelen": "Maatregelen (bron)"},
             reading_guide=GUIDE_PFAS, scale=10000),
]


def entries(chapter: Optional[str] = None, enabled_only: bool = True,
            only: Optional[Iterable[str]] = None) -> List[MapEntry]:
    """The catalogue, narrowed down. `only` is the study's map choice (`StudyResult.map_ids`):
    None means every entry that passes the other two filters, a list means exactly those ids.

    Every place that walks the catalogue for one study takes it - report pages, sources table,
    layers, legends, map images - because a map the user unchecked must cost nothing at all, not
    a layer, not a request and not a sheet that says "Bron niet beschikbaar".
    """
    wanted = None if only is None else set(only)
    return [e for e in CATALOGUE
            if (chapter is None or e.chapter == chapter) and (e.enabled or not enabled_only)
            and (wanted is None or e.id in wanted)]


def by_id(map_id: str) -> MapEntry:
    for e in CATALOGUE:
        if e.id == map_id:
            return e
    raise KeyError(map_id)
