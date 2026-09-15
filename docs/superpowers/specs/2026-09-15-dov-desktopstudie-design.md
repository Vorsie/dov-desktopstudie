# DOV Desktopstudie — ontwerp (2026-09-15)

QGIS-plugin die uit een adres, coördinaat of polygoon automatisch een geotechnische
desktopstudie voor Vlaanderen samenstelt: een QGIS-project met alle lagen én een PDF-rapport,
uitsluitend op basis van open data van DOV en geopunt.

## 1. Probleem en doel

Een desktopstudie (ligging, historiek, geologie, bestaand grondonderzoek, doorsnede,
aandachtspunten) kost vandaag uren klikwerk op DOV en geopunt plus knip-en-plakwerk in een
rapport. Doel: **zone opgeven → in minuten een QGIS-project met lagen + PDF**, elke keer dezelfde
bronnen en structuur. Vooral tijdswinst; daarnaast consistentie en volledigheid.

**Gebruikers:** geotechnici (auteur + collega's) zonder Python-kennis. Open source (GPL-2.0-or-later,
verplicht voor QGIS-plugins). Volledig nieuw en onafhankelijk project (clean room).

**Succes (v1):** QGIS-project met lagen in groepen per hoofdstuk **en** een neutrale PDF met logo,
bedrijfsnaam en auteur als instelling. Elke kaart heeft een titel, schaalbalk, noordpijl, legenda
(waar van toepassing) en twee infovakjes (rechtsboven: project/datum/bron/schaal; rechtsonder:
attributie/licentie/ophaaltijdstip).

**Buiten scope (blijvend):** berekeningen of ontwerp (draagkracht, zettingen, EC7, parameters);
eigen geologische interpretatie (de tool trekt zelf geen laaggrenzen; DOV-modellagen worden getoond
zoals DOV ze levert); bronnen buiten DOV/geopunt (geen bedrijfsarchief, Wallonië, Nederland,
betaalde data); Word/docx-uitvoer.

## 2. Omgeving en compatibiliteit

- Draait in de Python die QGIS meelevert: stdlib, `qgis.PyQt`, numpy, matplotlib. **Geen pip-installs**
  bij gebruikers, geen pydov, geen pyproj (alle services aanvaarden EPSG:31370, de kern rekent in
  Lambert 72).
- **QGIS 3.34 t/m 4.x.** `qgisMinimumVersion=3.34`, `supportsQt6=True`. Alleen API's die in 3.34
  bestaan; imports via `qgis.PyQt`; Qt-enums altijd scoped (`Qt.AlignmentFlag.AlignRight`) zodat
  PyQt5 én PyQt6 werken; Python-syntaxis ≥ 3.9 (geen `match`, geen geneste f-strings).
- Compatibiliteit wordt bewaakt: lokaal op een 3.x-installatie en op QGIS 4.x; CI draait de
  headless flow in Docker-images `qgis/qgis:release-3_34` en de actuele LTR.

## 3. Geverifieerde bronnen (live getest 2026-09-15)

| Doel | Service | Detail |
|---|---|---|
| Geocoder | `https://geo.api.vlaanderen.be/geolocation/v4/Location?q=<adres>&c=5` | JSON met `X_Lambert72`, `Y_Lambert72`, `FormattedAddress` |
| DOV WFS | `https://www.dov.vlaanderen.be/geoserver/wfs` (2.0.0, `outputFormat=application/json`, `srsName=EPSG:31370`) | Punten: `dov-pub:Sonderingen`, `dov-pub:Boringen`, `interpretaties:lithologische_beschrijvingen`, `interpretaties:gecodeerde_lithologie`, `interpretaties:geotechnische_coderingen`, `gw_meetnetten:grondwaterlocaties_met_metingen`. Kaartvlakken: `bodemkaart:bodemtypes`, `quartair:quartair_samengesteld_50k_legende`, `quartair:quartair_200k`, `neo_paleo:tertiair_50k`, `hcov:hcov_0100_vk`, `gw_bescherming:gwkwb_kwbschaal`, `ovam:uitspraak_bodemonderzoeken`, `plastische_gronden:IndexPlastisch`, `erosie:erosie_potentiele_bodemerosiekaart_per_perceel_2014`, `dov-pub:Quartair_Isopachen`. `CQL_FILTER=INTERSECTS(geom, POLYGON(...))` werkt. |
| DOV WMS | `https://www.dov.vlaanderen.be/geoserver/wms` (1.3.0) | o.a. `bodemkaart:bodemtypes`, `quartair:quartair_samengesteld`, `neo_paleo:tertiair_50k`, `hcov:hcov_0100_vk`, `gw_bescherming:gwkwb_kwbschaal`, `gxg:gxg`, `plastische_gronden:krimp_zwel`, `ovam:uitspraak_bodemonderzoeken`, `erosie:erosie_potentiele_bodemerosiekaart_per_perceel_2014`, `dov-pub:Quartair_Isopachen`. GetFeatureInfo (JSON) werkt; bbox-asvolgorde is x,y. |
| CPT-XML | `https://www.dov.vlaanderen.be/data/sondering/<permkey>.xml` | `sondeonderzoek/penetratietest/meetdata/{lengte,diepte|sondeerdiepte,qc,fs,u,Qt}`; qc in MPa, fs en u in kPa, Qt (totale weerstand) in kN; `diepte` (hellingsgecorrigeerd) verkiezen boven `lengte`; waarden mogen een `>`-prefix dragen (off-scale) |
| Boring-XML, lithologie | `/data/boring/<permkey>.xml` (header), `/data/interpretatie/<id>.xml` | `lithologischebeschrijving/laag/{van,tot,beschrijving}` |
| Peilputten | WFS-attributen (`peilmetingen_van/tot`, `aantal_dagen_sinds_laatste_meting`, `Aquifer_HCOVv2`, `onderkant_filter_m`, `stijghoogterapport`) + `/data/filter/<id>.xml` | `filtermeting/peilmeting/{datum,peil_mtaw,methode,betrouwbaarheid}` |
| Virtuele boring | `https://services.dov.vlaanderen.be/virtueleboringserver/base/virtueleprofielen/doorprik/<model>?x=&y=&crs=EPSG:31370` | modellen `g3dv3_F` (formaties), `g3dv3_L` (leden), `g3dv3_P` (periodes), `g3dv3_T` (tijdvakken), `hcovv1`, `hcovv2_H`, `hcovv2_S`, `hcovv2_B`. `data[]` = `{name, top, base, thickness}` in mTAW; `layers[]` = `code`, `name`, `beschrijving`, `dovlayercolor`, `texturen`. Top van de eerste laag = maaiveld. Profiel-endpoint: `lagenmodel/<model>/profielbevraging/lagen?xValues=&yValues=&resolution=` (diktes per afstand). |
| Basiskaarten | `https://geo.api.vlaanderen.be/GRB-basiskaart/wms` (`GRB_BSK`), `…/GRB/wms`, `…/OMWRGBMRVL/wms` (`Ortho`) | WMS 1.3.0, EPSG:31370 |
| Historische kaarten | `https://geo.api.vlaanderen.be/HISTCART/wms` | `ferraris`, `abw`, `vandermaelen`, `popp`; optioneel `villaret`, `frickx`, `Masse` |
| Oude orthofoto's | `…/OKZ/wms` (`OKZPAN71VL`, `OKZRGB79_90VL`), `…/OMW/wms` (`OMWRGB00_03VL`, `OMWRGB05_07VL`, `OMWRGB08_11VL`, …) | WMS 1.3.0 |
| Hoogte | `…/DHMV/wms` (`DHMVII_DTM_1m`, `DHMV_II_HILL_25cm`), `…/DHMV/wcs` coverage `DHMVII_DTM_1m` (WCS 2.0.1) | QGIS laadt WCS native |
| Topokaart NGI | `https://cartoweb.wms.ngi.be/service`, laag `topo` | actueel. Historische NGI-reeks (1873–1989): geen officiële open WMS → leeg, gedocumenteerd config-slot |
| Watertoets | `https://inspirepub.waterinfo.be/arcgis/services/informatieplicht/overstromingsgevoelige_gebieden_{pluviaal,fluviaal,vanuit_de_zee}/MapServer/WMSServer`, laag `0` | WMS + GetFeatureInfo; licentie "geen beperkingen" |

Geverifieerd maar (nog) niet in de catalogus: de watertoets-laag `vanuit_de_zee` en
`geo.api.vlaanderen.be/GRB/wms`.

Bekende eigenaardigheden van de DOV-services die de kern moet respecteren: `BBOX` en `CQL_FILTER`
nooit samen in één GetFeature (ruimtelijke predicaten in de CQL opnemen); grote resultaten via paging
met `startIndex`/`count` (page_size 500; op 2026-09-15 geen harde serverlimiet meer waargenomen), over
pagina's ontdubbelen op feature-id en afkapping door `max_features` loggen én in het rapport melden; DOV
adverteert EPSG:6190 maar de coördinaten zijn Lambert 72; de WCS-GetCoverage komt als multipart (GML + tiff).

## 4. Architectuur (hybride: pure-Python kern + dunne QGIS-schil)

```
dov-desktopstudie/
├── desktopstudie/                      ← plugin-map (wordt gezipt/geïnstalleerd)
│   ├── __init__.py (classFactory), metadata.txt, plugin.py
│   ├── core/                           PURE PYTHON: stdlib + numpy + matplotlib. GEEN qgis-imports.
│   │   ├── catalogue.py                kaartcatalogus: één entry per kaart (id, hoofdstuk, titel, wms_url,
│   │   │                               laag, formaat, opacity, attributie, legend, wfs_typename + feitenvelden, enabled)
│   │   ├── geometry.py                 buffer-polygoon, centroid, langste as, lijn verlengen, punten op lijn, bbox, afstand
│   │   ├── model.py                    dataclasses: StudyZone, Cpt, Borehole, GwFilter, VirtualBorehole, MapFact,
│   │   │                               Section, Signalering, StudyResult (+ provenance: url, tijdstip)
│   │   ├── services/http.py            urllib-wrapper: timeout, retry, user-agent, schijfcache in de uitvoermap
│   │   ├── services/geocoder.py        adres → L72-punt (+ kandidaten)
│   │   ├── services/dov_wfs.py         GetFeature JSON; INTERSECTS/DWITHIN; paging + ontdubbeling; afkapping gemeld
│   │   ├── services/dov_xml.py         CPT-, boring-, interpretatie-, filter-XML → model (xml.etree; eenheden)
│   │   ├── services/virtuele_boring.py doorprik per model; laagcatalogus (naam, kleur, texturen)
│   │   ├── checks.py                   signaleringsregels: StudyResult → list[Signalering]
│   │   ├── figures/                    matplotlib (Agg): cpt_figure, borehole_column, vb_column, section_figure
│   │   ├── report_content.py           rapportboom (hoofdstukken, tabellen als rijen, figuurpaden, teksten) — geen rendering
│   │   └── study.py                    orchestrator: run(zone, settings, progress_cb) → StudyResult; schrijft data/ en figuren/
│   ├── qgis/                           DUNNE SCHIL (qgis.core, qgis.gui, qgis.PyQt)
│   │   ├── dialog.py (+ .ui)           tabs Locatie | Instellingen | Rapport
│   │   ├── map_tools.py                polygoon- en lijntekentool
│   │   ├── layers.py                   WMS-rasterlagen uit catalogus, memory-lagen uit model, groepen per hoofdstuk, .qml-stijlen
│   │   ├── dem.py                      DHMV WCS-laag → zonale statistiek maaiveld + hoogteprofiel langs de doorsnedelijn
│   │   ├── layout.py                   multi-page QgsLayout uit paginasjabloon (kaart, schaalbalk, noordpijl, legenda, infovakjes)
│   │   ├── export.py                   QgsLayoutExporter → PDF (+ PNG per pagina), .qgz opslaan, GeoPackage
│   │   ├── task.py                     QgsTask: core.study.run in de achtergrond; lagen + layout daarna op de main thread
│   │   └── settings.py                 QgsSettings: logo, bedrijf, auteur, standaardstraal, uitvoermap
│   └── resources/                      iconen, noordpijl.svg, paginasjabloon.qpt, stijlen/*.qml
├── tests/core/                         pytest op gewone Python; fixtures = opgeslagen echte responses; `-m live` voor echte services
├── scripts/run_headless.py             volledige flow via standalone QgsApplication → PDF + PNG's
├── docs/superpowers/specs/             dit ontwerp
├── .github/workflows/ci.yml            ruff + pytest (kern) op Python 3.12; headless flow in QGIS-containers
└── CLAUDE.md, README.md, LICENSE (GPL-2.0-or-later), CHANGELOG.md, pyproject.toml (alleen dev-tooling)
```

Waarom: de kern is met pytest testbaar zonder QGIS; de schil levert GIS-kwaliteit (echte kaartframes,
legenda's via GetLegendGraphic, schaalbalk, noordpijl); het QGIS-project ontstaat vanzelf omdat alle
lagen echte QGIS-lagen zijn. Nieuwe kaarten toevoegen = één catalogus-entry.

## 5. Dataflow

1. **Zone** (dialoog): adres → geocoder → punt + buffer (standaard 50 m) | X/Y + buffer | getekende
   polygoon | geselecteerd feature (door de schil naar 31370 getransformeerd). Resultaat:
   `StudyZone(polygon_l72, naam, straal, doorsnedelijn)`. Doorsnedelijn: standaard de langste as van
   de zone, beide zijden verlengd (standaard 100 m); optioneel zelf tekenen of uit een laag kiezen.
2. **Ophalen** (QgsTask → `core.study.run`): WFS-punten binnen `DWITHIN(straal)` (CPT, boringen,
   peilputten, interpretaties); XML-details voor de dichtstbijzijnde N per type (max 4 threads);
   virtuele boringen op het representatieve punt van de zone (de centroid als die binnen de zone ligt, anders een punt op de breedste koorde; `g3dv3_L`, `hcovv2_S`) en op M punten langs de doorsnedelijn
   (`g3dv3_F`); kaartfeiten via WFS `INTERSECTS(zone)` per catalogus-entry met `wfs_typename`;
   watertoets via GetFeatureInfo op het representatieve punt en de hoekpunten. Elke bron faalt **geïsoleerd**: fout →
   `Signalering("bron niet beschikbaar")` + log; het rapport gaat door.
3. **Figuren** (kern, matplotlib Agg → PNG in `figuren/`): qc/fs/Rf-diagram per CPT, lithologiekolom
   per boring, virtuele-boringkolom, doorsnede (formaties in `dovlayercolor`, maaiveldlijn uit de
   toppen, proeven binnen een corridor geprojecteerd als markers, zone-extent gearceerd).
4. **QGIS-project** (schil, main thread): groepen per hoofdstuk; WMS-lagen uit de catalogus;
   memory-lagen (zone, straalcirkel, doorsnedelijn, CPT/boringen/peilputten/virtuele boringen met
   attributen en DOV-links), ook weggeschreven naar `data/studie.gpkg`; DHMV WCS-laag + zonale
   statistiek.
5. **Rapport** (schil): één multi-page `QgsLayout` uit `paginasjabloon.qpt`. Kaartpagina = kaartitem
   op de standaardschaal van de kaart uit de catalogus (`scale`, bv. 1:2 500 voor GRB, 1:25 000 voor
   Ferraris omdat lage-resolutiekaarten verder uitgezoomd leesbaar zijn); de schil zoomt alleen verder
   uit als de zone anders niet in het kader past + titel + schaalbalk + noordpijl + legenda
   (als `legend: true`) + infovak rechtsboven + infovak rechtsonder. Figuurpagina = afbeelding +
   onderschrift. Tabelpagina = `QgsLayoutItemTextTable`. Tekstpagina = HTML-label. Export via
   `QgsLayoutExporter` naar `rapport.pdf` en PNG per pagina (controle).
6. **Uitvoermap** `<uitvoer>/<projectnaam>_<yyyymmdd>/`: `studie.qgz`, `rapport.pdf`,
   `pagina_XX.png`, `data/` (studie.json, studie.gpkg, cache van XML/JSON), `figuren/`, `log.txt`.
   Herdraaien met cache slaat downloads over.

## 6. Rapportstructuur (v1)

0. Titelblad (logo, bedrijf, project, adres/coördinaten, datum, auteur, disclaimer "verzameling van
   open data, geen interpretatie of ontwerp"), inhoud, bronnenlijst met licenties. Gerealiseerd als
   `Report.meta` (titelblad-gegevens) plus hoofdstuk 8 (bronnen).
1. **Ligging en topografie**: GRB, orthofoto, NGI-topo, DHMV-hillshade + DTM; feiten: gemeente,
   oppervlakte, centroid, maaiveld min/max/gemiddeld.
2. **Historische kaarten**: Ferraris, Buurtwegen, Vandermaelen, Popp, ortho 1971, 1979–90, 2000–03
   (elk op de eigen catalogus-schaal, want lage-resolutiekaarten zijn verder uitgezoomd leesbaar; zone-omtrek
   erop); slot "NGI historische topokaarten (geen open WMS)".
3. **Geologie en bodem**: bodemkaart, Quartair (samengesteld 1/50 000) + Quartairdikte, Tertiair
   (1/50 000), HCOV, grondwaterkwetsbaarheid, GxG, watertoets pluviaal/fluviaal, erosie, krimp-zwel,
   OVAM-uitspraken; per kaart een tabel met de kaarteenheden die de zone snijden.
4. **Virtuele boring** op het representatieve punt van de zone: G3Dv3 formaties + leden (top/basis
   mTAW, dikte), HCOV; kolomfiguur.
5. **Grondonderzoek DOV** binnen de straal: overzichtskaart met gelabelde punten; tabellen CPT /
   boringen / peilputten (afstand, diepte, datum, methode, uitvoerder, opdracht, DOV-link);
   bijlagen: qc-diagrammen (N dichtstbijzijnde CPT's, standaard 5), lithologiekolommen (N boringen,
   standaard 5), laatste peil per peilput.
6. **Doorsnede**: inzetkaart met de lijn (GRB, 1:5 000) + doorsnedefiguur (kolommen op hun echte
   afstand langs de lijn, ook als een doorprik-punt ontbreekt; verticale overdrijving in de titel).
7. **Samenvatting en aandachtspunten**: feitentabel + signaleringen (feit — bron — "aandachtspunt
   voor het grondonderzoek: …") + vaste tekst met beperkingen.

## 7. Signaleringsregels v1

Zuiver data-gedreven, elk een pure functie in `checks.py`, geformuleerd in de woorden van de regel:

- antropogeen/ophoging aanwezig in de virtuele boring;
- klei-, veen- of leemeenheid binnen 10 m onder maaiveld (trefwoord in `texturen`);
- top Tertiair minder dan 3 m onder maaiveld;
- bodemkaart: natte drainageklasse; veen- of kleitextuur; OB/ON (bebouwd, opgehoogd of vergraven);
- ondiepste recente grondwaterstand minder dan 2 m onder maaiveld (nabijste peilput met meting);
- zone overstromingsgevoelig (pluviaal of fluviaal);
- erosieklasse hoog of zeer hoog;
- krimp-zwelgevoelige gronden;
- OVAM-bodemonderzoek in of naast de zone;
- geen CPT binnen de straal / wel CPT binnen 50 m;
- reliëfverschil in de zone groter dan 2 m;
- bron niet bereikbaar;
- `grondverschuiving_gevoelig`: gevoeligheid klasse ≥ 2;
- `grondverschuiving_gekarteerd`: gekarteerde grondverschuiving in de zone;
- `pfas_no_regret`: PFAS-no-regretzone over de zone;
- `wfs_afgekapt`: WFS-resultaat afgekapt door max_features;
- `doorsnede_onvolledig`: doorprik-punten mislukt.

Historische kaarten krijgen een vaste manuele checklist-tekst (vijvers, waterlopen, bebouwing,
vergravingen); er is geen beeldinterpretatie.

## 8. Foutafhandeling en logging

Console-wrapper met vaste prefixen `[core INFO module]` / `[qgis INFO module]`, naar QgsMessageLog
én `log.txt` in de uitvoermap. Per fase een INFO-samenvatting ("12 CPT's, 3 zonder XML"), per item
DEBUG. Wat NIET gevonden is wordt expliciet gelogd én in het rapport benoemd.

## 9. Verificatie

- Kern: `pytest tests/core` groen (CI, Python 3.12); `pytest -m live` handmatig tegen de echte
  services.
- Figuren: PNG's openen en bekijken; niet vertrouwen op "test groen".
- Plugin: in QGIS laden, alle vier de invoermodi doorlopen, project + PDF maken voor Gent
  (X 104326, Y 192506) en een landelijke locatie; PNG-pagina's controleren op titel, schaalbalk,
  noordpijl, legenda, infovakjes en zone-omtrek; aantallen CPT/boringen/peilputten binnen 500 m
  vergelijken met de DOV-verkenner.
- Robuustheid: één bron uitschakelen (foute URL in de catalogus) → rapport komt toch, met de
  signalering "bron niet beschikbaar".
- Compatibiliteit: headless flow in `qgis/qgis:release-3_34` en de actuele LTR; handmatig op QGIS 4.x.
