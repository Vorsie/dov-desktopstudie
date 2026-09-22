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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# The service addresses come from the catalogue, never from a copy here: a fixture is only a
# record of what the CODE asks, so a URL that moved has to move in one place. `catalogue` is pure
# stdlib, so this script stays runnable on any Python >= 3.9 without the rest of the package.
from desktopstudie.core import catalogue  # noqa: E402

FIXTURE_DIR = ROOT / "tests" / "core" / "fixtures"
WFS = catalogue.DOV_WFS_URL
GXG = catalogue.dov_wms("gxg:gxg")[0]
VB_PROFILE = catalogue.VB_PROFILE_URL
WATERINFO = catalogue.WATERINFO_WMS_URL
GEOCODE_QUERY = "Kortrijksesteenweg 100 Gent"
DOORPRIK_POINT = {"x": 104326, "y": 192506, "crs": "EPSG:31370"}
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


def wfs(typename: str, cql: str, count: int = 5, extra: dict | None = None) -> str:
    """One GetFeature, asked exactly the way `core.services.dov_wfs` asks it.

    In particular WITHOUT `propertyName`. Naming the properties makes GeoServer answer
    `"geometry": null` on every feature, and a fixture whose rows carry no geometry cannot be
    measured against - `study._nearest_rows` skips exactly those rows. A fixture that does not
    look like the live answer is a test that passes for the wrong reason.
    """
    params = {
        "service": "WFS", "version": "2.0.0", "request": "GetFeature",
        "typeNames": typename, "outputFormat": "application/json",
        "srsName": "EPSG:31370", "CQL_FILTER": cql, "count": str(count),
    }
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


def doorprik(model: str) -> str:
    """One virtual borehole at the study point, the way `virtuele_boring` asks for it."""
    return catalogue.VB_DOORPRIK_URL.format(model=model) + "?" + urllib.parse.urlencode(
        DOORPRIK_POINT, quote_via=urllib.parse.quote)


def geocode(query: str) -> str:
    return catalogue.GEOCODER_URL + "?" + urllib.parse.urlencode(
        {"q": query, "c": 5}, quote_via=urllib.parse.quote)


def dwithin(m: int, extra_cql: str = "") -> str:
    return f"DWITHIN(geom,{ZONE},{m},meters)" + (f" AND {extra_cql}" if extra_cql else "")


FIXTURES: list[tuple[str, str]] = [
    ("geocoder_kortrijksesteenweg.json", geocode(GEOCODE_QUERY)),
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
     wfs("neo_paleo:tertiair_50k", f"INTERSECTS(shape,{ZONE})")),
    ("wfs_hcov_0100_vk_intersects.json",
     wfs("hcov:hcov_0100_vk", f"INTERSECTS(geometry,{ZONE})")),
    ("wfs_gwkwb_kwbschaal_intersects.json",
     wfs("gw_bescherming:gwkwb_kwbschaal", f"INTERSECTS(shape,{ZONE})")),
    ("wfs_ovam_uitspraak_intersects.json",
     wfs("ovam:uitspraak_bodemonderzoeken", f"INTERSECTS(geom,{ZONE})")),
    ("wfs_erosie_2014_intersects.json",
     wfs("erosie:erosie_potentiele_bodemerosiekaart_per_perceel_2014",
         f"INTERSECTS(the_geom,{ZONE_RURAL})", 5)),
    ("wfs_erosie_2014_hoog.json",
     wfs("erosie:erosie_potentiele_bodemerosiekaart_per_perceel_2014",
         f"INTERSECTS(the_geom,{ZONE_EROSIE_HOOG})", 5)),
    # A contour never overlaps a plot, so this one is asked with DWITHIN, and the distance the
    # report prints comes from the geometry in the answer. The geometry field of this layer is
    # `geom`, not `geometry`, and the study zone itself has contours within a few hundred metres,
    # so ZONE serves where the coarse layer needed a rural square.
    ("wfs_quartair_isopachen_dwithin.json",
     wfs("quartair:qisopachen_quartair_50k", f"DWITHIN(geom,{ZONE},2000,meters)", 5)),
    # The one exception to the rule in `wfs`, and a measured one: this layer answers a 1 km square
    # with a SINGLE feature whose geometry is 40 MB - the susceptibility polygon covers most of
    # Flanders - and a 40 MB fixture is not a fixture. So this request keeps `propertyName` and
    # its features come back with `"geometry": null`. That is safe only while this map is asked
    # with INTERSECTS; give it a `fact_within_m` and the distance can no longer be measured, so
    # the fixture would have to go (or the query would have to find a smaller polygon first).
    ("wfs_grndversch_gevoeligh_intersects.json",
     wfs("grondverschuivingen:grndversch_gevoeligh", f"INTERSECTS(shape,{ZONE_RURAL})", 5,
         extra={"propertyName": "ogc_fid,gevoelighd,klasse"})),
    ("wfs_grndversch_gekarteerd_intersects.json",
     wfs("grondverschuivingen:grndversch_gekarteerd", f"INTERSECTS(shape,{ZONE_GRONDVERSCHUIVING})", 5)),
    # WFS pfas:no_regret_huidig; the WMS "no_regret_zones" is a STYLE of that same layer, not a
    # layer of its own (live check 2026-09-15: GetMap on pfas:no_regret_zones -> LayerNotDefined).
    ("wfs_pfas_no_regret_intersects.json",
     wfs("pfas:no_regret_huidig", f"INTERSECTS(geom,{ZONE_PFAS})", 5)),
    ("sondering_1965-039716.xml", "https://www.dov.vlaanderen.be/data/sondering/1965-039716.xml"),
    ("sondering_2024-090319.xml", "https://www.dov.vlaanderen.be/data/sondering/2024-090319.xml"),
    ("interpretatie_2016-252456.xml", "https://www.dov.vlaanderen.be/data/interpretatie/2016-252456.xml"),
    ("interpretatie_2024-382762.xml", "https://www.dov.vlaanderen.be/data/interpretatie/2024-382762.xml"),
    ("filter_1985-007948.xml", "https://www.dov.vlaanderen.be/data/filter/1985-007948.xml"),
    ("vb_g3dv3_F.json", doorprik("g3dv3_F")),
    ("vb_g3dv3_L.json", doorprik("g3dv3_L")),
    ("vb_g3dv3_P.json", doorprik("g3dv3_P")),
    ("vb_hcovv2_S.json", doorprik("hcovv2_S")),
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
