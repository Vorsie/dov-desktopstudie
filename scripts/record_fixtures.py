"""Record real service responses as test fixtures.

Run:  python scripts/record_fixtures.py
Writes tests/core/fixtures/<name> and a README.md with URL + retrieval date per file.
Only stdlib; usable from any Python >= 3.9.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "tests" / "core" / "fixtures"
WFS = "https://www.dov.vlaanderen.be/geoserver/wfs"
GXG = "https://www.dov.vlaanderen.be/geoserver/gxg/wms"
VB = "https://services.dov.vlaanderen.be/virtueleboringserver/base/virtueleprofielen/doorprik/"
VB_PROFILE = ("https://services.dov.vlaanderen.be/virtueleboringserver/base/lagenmodel/"
              "{model}/profielbevraging/lagen")
WATERINFO = (
    "https://inspirepub.waterinfo.be/arcgis/services/informatieplicht/"
    "overstromingsgevoelige_gebieden_{kind}/MapServer/WMSServer"
)
ZONE = "POLYGON((104226 192406,104426 192406,104426 192606,104226 192606,104226 192406))"
# Rural, erosion-prone square (1000 x 1000 m) in the Flemish Ardennes near Kluisbergen/Ronse,
# picked because it is the one place a live probe found both the erosie- and the (sparse)
# isopachen-layer returning numberMatched > 0 for the same square.
ZONE_RURAL = "POLYGON((89500 181500,90500 181500,90500 182500,89500 182500,89500 181500))"
# Square (500 x 500 m) near Kluisbergen/Ronse where a live probe found a parcel with
# Totale_erosie "hoog" among the first 5 results, for a fixture-driven erosie:hoog test.
ZONE_EROSIE_HOOG = "POLYGON((99750 164750,100250 164750,100250 165250,99750 165250,99750 164750))"
# Square (3 x 3 km) around Maarkedal/Oudenaarde (Koppenberg, Nukerke) in the Flemish Ardennes:
# the first square of a 3 km grid walked out from 95000/165000 that has mapped landslides
# (numberMatched 8 on 2026-09-15).
ZONE_GRONDVERSCHUIVING = "POLYGON((95000 165000,98000 165000,98000 168000,95000 168000,95000 165000))"
# Square (3 x 3 km) around Zwijndrecht, where the PFAS no-regret zones cluster (numberMatched 5).
ZONE_PFAS = "POLYGON((144500 209500,147500 209500,147500 212500,144500 212500,144500 209500))"


def wfs(
    typename: str,
    cql: str,
    count: int = 5,
    extra: dict | None = None,
    props: tuple[str, ...] = (),
) -> str:
    params = {
        "service": "WFS", "version": "2.0.0", "request": "GetFeature",
        "typeNames": typename, "outputFormat": "application/json",
        "srsName": "EPSG:31370", "CQL_FILTER": cql, "count": str(count),
    }
    if props:
        params["propertyName"] = ",".join(props)
    params.update(extra or {})
    return WFS + "?" + urllib.parse.urlencode(params, quote_via=urllib.parse.quote)


def describe(typename: str) -> str:
    params = {"service": "WFS", "version": "2.0.0", "request": "DescribeFeatureType",
              "typeNames": typename, "outputFormat": "application/json"}
    return WFS + "?" + urllib.parse.urlencode(params, quote_via=urllib.parse.quote)


def gfi(kind: str, x: int, y: int) -> str:
    h = 100
    params = {
        "service": "WMS", "version": "1.3.0", "request": "GetFeatureInfo",
        "layers": "0", "query_layers": "0", "crs": "EPSG:31370",
        "bbox": f"{x - h},{y - h},{x + h},{y + h}", "width": "201", "height": "201",
        "i": "100", "j": "100", "info_format": "application/geo+json", "feature_count": "5",
    }
    query = urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
    return WATERINFO.format(kind=kind) + "?" + query


def gxg(layer: str, x: float, y: float) -> str:
    """GetFeatureInfo on one of the two mean groundwater levels, at the point the report asks
    about. The value comes back as `<GHG|GLG>-waarde_m-mv`: metres below ground level."""
    h = 25.0
    params = {
        "service": "WMS", "version": "1.1.1", "request": "GetFeatureInfo",
        "layers": layer, "query_layers": layer, "styles": "gxg:gxg", "srs": "EPSG:31370",
        "bbox": f"{x - h},{y - h},{x + h},{y + h}", "width": "101", "height": "101",
        "x": "50", "y": "50", "info_format": "application/json", "feature_count": "5",
    }
    return GXG + "?" + urllib.parse.urlencode(params, quote_via=urllib.parse.quote)


def vb_profile(model: str, p: tuple[float, float], q: tuple[float, float], resolution: int) -> str:
    """Profile query along p -> q; the same line the section tests use."""
    params = {"xValues": f"{p[0]:.2f},{q[0]:.2f}", "yValues": f"{p[1]:.2f},{q[1]:.2f}",
              "resolution": str(resolution)}
    return VB_PROFILE.format(model=model) + "?" + urllib.parse.urlencode(params,
                                                                        quote_via=urllib.parse.quote)


def dwithin(m: int, extra_cql: str = "") -> str:
    return f"DWITHIN(geom,{ZONE},{m},meters)" + (f" AND {extra_cql}" if extra_cql else "")


FIXTURES: list[tuple[str, str]] = [
    ("geocoder_kortrijksesteenweg.json",
     "https://geo.api.vlaanderen.be/geolocation/v4/Location?q=Kortrijksesteenweg%20100%20Gent&c=5"),
    ("wfs_describe_sonderingen.json", describe("dov-pub:Sonderingen")),
    ("wfs_describe_tertiair_50k.json", describe("neo_paleo:tertiair_50k")),
    ("wfs_sonderingen_dwithin.json", wfs("dov-pub:Sonderingen", dwithin(500))),
    ("wfs_sonderingen_page2.json",
     wfs("dov-pub:Sonderingen", dwithin(500), 5, {"startIndex": "5"})),
    # boringen met een lithologische beschrijving, zodat de interpretatie-fixture er zeker bij past
    ("wfs_boringen_dwithin.json",
     wfs("dov-pub:Boringen", dwithin(500, "lithologische_beschrijving=true"))),
    # alle interpretaties binnen 500 m (count 200 > aantal), zodat elke boring hierboven matcht
    ("wfs_lithologische_beschrijvingen_dwithin.json",
     wfs("interpretaties:lithologische_beschrijvingen", dwithin(500), 200)),
    ("wfs_gecodeerde_lithologie_dwithin.json",
     wfs("interpretaties:gecodeerde_lithologie", dwithin(500), 200)),
    # peilputten die effectief peilmetingen hebben
    ("wfs_grondwaterlocaties_dwithin.json",
     wfs("gw_meetnetten:grondwaterlocaties_met_metingen",
         dwithin(2500, "peilmetingen_tot IS NOT NULL"), 10)),
    ("wfs_bodemtypes_intersects.json", wfs("bodemkaart:bodemtypes", f"INTERSECTS(geom,{ZONE})")),
    ("wfs_quartair_samengesteld_intersects.json",
     wfs("quartair:quartair_samengesteld_50k_legende", f"INTERSECTS(geom,{ZONE})")),
    ("wfs_quartair_200k_intersects.json",
     wfs("quartair:quartair_200k", f"INTERSECTS(geom,{ZONE})")),
    ("wfs_tertiair_50k_intersects.json",
     wfs("neo_paleo:tertiair_50k", f"INTERSECTS(shape,{ZONE})",
         props=("dataengine_id", "code", "formatie", "lid", "beschrijving", "typeov", "volgorde"))),
    ("wfs_hcov_0100_vk_intersects.json",
     wfs("hcov:hcov_0100_vk", f"INTERSECTS(geometry,{ZONE})",
         props=("id", "hcov_code", "hcov_naam"))),
    ("wfs_gwkwb_kwbschaal_intersects.json",
     wfs("gw_bescherming:gwkwb_kwbschaal", f"INTERSECTS(shape,{ZONE})")),
    ("wfs_ovam_uitspraak_intersects.json",
     wfs("ovam:uitspraak_bodemonderzoeken", f"INTERSECTS(geom,{ZONE})")),
    ("wfs_indexplastisch_intersects.json",
     wfs("plastische_gronden:IndexPlastisch", f"INTERSECTS(geom,{ZONE})",
         props=("id", "code_H3Dv2_0", "Eenheid_G3Dv3_0", "code_G3Dv3_0", "hoofdlithologie"))),
    ("wfs_erosie_2014_intersects.json",
     wfs("erosie:erosie_potentiele_bodemerosiekaart_per_perceel_2014",
         f"INTERSECTS(the_geom,{ZONE_RURAL})", 5,
         props=("gid", "Erosieklasse_ALV", "Totale_erosie", "Watererosie", "Bewerkingserosie"))),
    ("wfs_erosie_2014_hoog.json",
     wfs("erosie:erosie_potentiele_bodemerosiekaart_per_perceel_2014",
         f"INTERSECTS(the_geom,{ZONE_EROSIE_HOOG})", 5,
         props=("gid", "Erosieklasse_ALV", "Totale_erosie", "Watererosie", "Bewerkingserosie"))),
    # A contour never overlaps a plot, so this one is asked with DWITHIN - and WITHOUT
    # propertyName: asking for named properties makes GeoServer answer "geometry": null on every
    # feature, and the distance the report prints is measured from that geometry.
    ("wfs_quartair_isopachen_dwithin.json",
     wfs("dov-pub:Quartair_Isopachen", f"DWITHIN(geometry,{ZONE_RURAL},10000,meters)", 5)),
    ("wfs_grndversch_gevoeligh_intersects.json",
     wfs("grondverschuivingen:grndversch_gevoeligh", f"INTERSECTS(shape,{ZONE_RURAL})", 5,
         props=("ogc_fid", "gevoelighd", "klasse"))),
    ("wfs_grndversch_gekarteerd_intersects.json",
     wfs("grondverschuivingen:grndversch_gekarteerd", f"INTERSECTS(shape,{ZONE_GRONDVERSCHUIVING})", 5,
         props=("dataengine_id", "type", "naam", "gemeente", "helling", "rapport"))),
    # WFS pfas:no_regret_huidig; the WMS "no_regret_zones" is a STYLE of that same layer, not a
    # layer of its own (live check 2026-09-15: GetMap on pfas:no_regret_zones -> LayerNotDefined).
    ("wfs_pfas_no_regret_intersects.json",
     wfs("pfas:no_regret_huidig", f"INTERSECTS(geom,{ZONE_PFAS})", 5,
         props=("id", "pfasdossiernr", "gemeente", "straat", "nrm_status_zone", "zone_geldig_vanaf",
                "no_regret_maatregelen"))),
    ("sondering_1965-039716.xml", "https://www.dov.vlaanderen.be/data/sondering/1965-039716.xml"),
    ("sondering_2024-090319.xml", "https://www.dov.vlaanderen.be/data/sondering/2024-090319.xml"),
    ("interpretatie_2016-252456.xml", "https://www.dov.vlaanderen.be/data/interpretatie/2016-252456.xml"),
    ("interpretatie_2024-382762.xml", "https://www.dov.vlaanderen.be/data/interpretatie/2024-382762.xml"),
    ("filter_1985-007948.xml", "https://www.dov.vlaanderen.be/data/filter/1985-007948.xml"),
    ("vb_g3dv3_F.json", VB + "g3dv3_F?x=104326&y=192506&crs=EPSG:31370"),
    ("vb_g3dv3_L.json", VB + "g3dv3_L?x=104326&y=192506&crs=EPSG:31370"),
    ("vb_g3dv3_P.json", VB + "g3dv3_P?x=104326&y=192506&crs=EPSG:31370"),
    ("vb_hcovv2_S.json", VB + "hcovv2_S?x=104326&y=192506&crs=EPSG:31370"),
    ("vb_profile_g3dv3_F.json",
     vb_profile("g3dv3_F", (104126.0, 192506.0), (104526.0, 192506.0), 100)),
    ("gxg_ghg_hit.json", gxg("gxg:ghg_mmv_main", 104326.8, 192506.7)),
    ("gxg_glg_hit.json", gxg("gxg:glg_mmv_main", 104326.8, 192506.7)),
    ("watertoets_fluviaal_hit.json", gfi("fluviaal", 102000, 191500)),
    ("watertoets_pluviaal_empty.json", gfi("pluviaal", 104326, 192506)),
]


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "dov-desktopstudie/fixtures"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read()


def validate(name: str, data: bytes) -> None:
    """Raise ValueError with a short reason if the body is not a usable fixture."""
    if b"ExceptionReport" in data or b"ServiceException" in data:
        raise ValueError("service returned an exception report")
    if name.endswith(".json"):
        json.loads(data)
    elif name.endswith(".xml"):
        ET.fromstring(data)


def main() -> int:
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    today = dt.date.today().isoformat()
    intro = "Echte antwoorden van de services, opgenomen met `scripts/record_fixtures.py`."
    lines = ["# Fixtures", "", intro, "", "| Bestand | Bron-URL | Datum |", "|---|---|---|"]
    failed = 0
    for name, url in FIXTURES:
        try:
            data = fetch(url)
            validate(name, data)
        except Exception as exc:  # noqa: BLE001 - report and continue
            reason = str(exc)
            print(f"FAIL {name}: {reason}")
            failed += 1
            note = f"MISLUKT op {today}: {reason}; bestand op schijf komt van een eerdere run"
            lines.append(f"| `{name}` | <{url}> | {note} |")
            continue
        (FIXTURE_DIR / name).write_bytes(data)
        print(f"ok   {name} ({len(data)} bytes)")
        lines.append(f"| `{name}` | <{url}> | {today} |")
    (FIXTURE_DIR / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
