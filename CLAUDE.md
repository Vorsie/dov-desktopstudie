# DOV Desktopstudie — projectinstructies

QGIS-plugin die uit een adres, coördinaat of polygoon een geotechnische desktopstudie voor
Vlaanderen samenstelt: QGIS-project met lagen + PDF-rapport, uitsluitend uit open data van DOV en
geopunt. Ontwerp: `docs/superpowers/specs/2026-09-15-dov-desktopstudie-design.md` (lees dat eerst).

Onafhankelijk, open-source project (GPL-2.0-or-later). Clean room: kopieer geen code uit andere
lokale projecten; alleen publiek gedocumenteerde service-eigenaardigheden mogen worden hergebruikt.

## Architectuur in één alinea

`desktopstudie/core/` is **pure Python** (stdlib + numpy + matplotlib, GEEN `qgis`- of
`PyQt`-import) en bevat catalogus, geometrie, datamodel, services (geocoder, DOV WFS, DOV XML,
virtuele boring, WMS GetFeatureInfo/watertoets), doorsnede (`section.py`: doorsnedelijn +
doorprik-ankers + het dichte DOV-profiel gestapeld op het modelmaaiveld + projectie van
CPT/boring/peilput binnen de corridor), figuren
(`figures/`: `common.py` zet de headless Agg-backend op; `cpt_figure.py`, `borehole_column.py`,
`vb_column.py`, `section_figure.py` schrijven PNG's), signaleringsregels (`checks.py`),
rapportinhoud (`report_content.py`: bouwt de hoofdstuk/pagina-boom - `Chapter` met `MapPage` /
`FigurePage` / `TablePage` / `TextPage` - uit een `StudyResult`; rendert zelf niets, dat doet de
schil) en de orchestrator `study.py`.
`desktopstudie/qgis/` is de dunne schil: dialoog, kaarttools, lagen, DEM, layout, export,
QgsTask, instellingen. Kaarten staan uitsluitend in `core/catalogue.py`: één entry per kaart;
een kaart toevoegen = één entry, geen code.

## Harde regels

- **Geen qgis-import in `core/`.** Bewaakt door `tests/core/test_no_qgis_imports.py`.
- **Compatibel met QGIS 3.34 t/m 4.x.** `qgisMinimumVersion=3.34`, `supportsQt6=True`. Alleen
  API's die in 3.34 bestaan. Imports via `qgis.PyQt`. Qt-enums altijd scoped
  (`Qt.AlignmentFlag.AlignRight`, `QDialog.DialogCode.Accepted`). Python-syntaxis ≥ 3.9: geen
  `match`, geen geneste f-strings, `from __future__ import annotations` in elk bestand. QGIS
  3.34/3.40 op Windows leveren Python 3.12; de 3.9-syntaxisregel blijft als ondergrens en CI test
  ook op 3.9.
- **Geen extra packages.** Alleen wat QGIS meelevert. Geen pydov, geen pyproj, geen requests
  (gebruik `urllib`). Alles rekent in EPSG:31370.
- **Bronnen live verifiëren.** Een laagnaam, veldnaam of URL komt pas in de catalogus of een parser
  nadat hij tegen de echte service is gecontroleerd. Fixtures in `tests/core/fixtures/` zijn echte
  opgeslagen antwoorden (met bron-URL en datum in een `README.md` ernaast).
- **Virtuele boring: twee endpoints.** `doorprik` geeft één punt met absolute peilen (top/base in
  mTAW). `profielbevraging/lagen` geeft een hele lijn, maar per afstandsstap uitsluitend **diktes**
  per laagcode (0.0 = laag afwezig) - dus zelf stapelen van bovenaf. Elke kolom is opgevuld tot één
  gemeenschappelijke modelbodem, gerapporteerd als `minValue`, waardoor `minValue + som(diktes)`
  exact het gemodelleerde maaiveld is (live geverifieerd tegen de doorprik op 17 punten over 78 km,
  2026-09-15).
  - Alleen `dist` (de afstand langs de lijn) is géén dikte. **`INV` is er wél een**: het is de
    *onderopvulling* van modellen met `knownLowBoundary: true` (bv. `hcovv1`), van de echte
    modelbodem tot `minValue`. Het telt dus mee in de som die het maaiveld geeft, maar wordt nooit
    getekend. Op de fixture-lijn loopt `INV` van 0,00 tot 1,05 m; alleen mét `INV` komen de
    doorprik-tops 8,38 / 11,55 / 14,59 / 17,79 / 21,36 mTAW eruit.
  - `maxValue` is het hoogste maaiveld langs de lijn; gebruik het als zelfcontrole. Wijkt
    `max(gestapelde maaivelden)` er meer dan 0,05 m van af, dan klopt de datum-aanname niet:
    WARNING en terugvallen op de doorprik-ankers.
  - Een kolom waarin élke dikte 0.0 is, ligt buiten het model: overslaan (chainage in de WARNING),
    geen kolom van nul hoogte op de modelbodem tekenen.
  - Het G3Dv3-raster is 100 m: fijner bevragen herhaalt dezelfde cel, dus een maaiveld dat *tussen*
    ankers wordt geïnterpoleerd kantelt de laaggrenzen binnen één cel en springt terug op de
    celrand.
- **Een WMS-naam kan een stijl zijn, geen laag.** `pfas:no_regret_zones` staat wel in de
  GetCapabilities maar als `<Style>` van de laag `pfas:no_regret_huidig`; een GetMap erop geeft
  `LayerNotDefined`. Controleer een nieuwe kaartlaag altijd met een echte GetMap, niet met een
  grep op de capabilities.
- **DOV-eigenaardigheden**: `BBOX` en `CQL_FILTER` nooit samen; paging met startIndex/count (geen
  harde 500-limiet meer waargenomen op 2026-09-15; page_size=500 als veilige default); features
  over pagina's ontdubbelen op id; afkapping door max_features wordt gelogd en in het rapport
  gemeld; CPT qc in MPa, fs/u in kPa, Qt (totale weerstand) in kN; WCS-GetCoverage is multipart.
- **`xml.etree.ElementTree`-valkuil bij DOV-XML.** `Element.iter(tag)` doet exacte tag-matching en
  ondersteunt het `{*}naam`-namespace-jokerteken NIET (dat werkt alleen in de ElementPath-syntax
  van `find`/`findall`/`iterfind`); gebruik dus `root.findall(".//{*}tag")`, nooit
  `root.iter("{*}tag")` — anders levert de parser stilzwijgend een lege lijst op.
- **Elke bron faalt geïsoleerd.** Een falende service geeft een `Signalering("bron niet
  beschikbaar")` en een logregel; het rapport gaat door. Nooit stil overslaan.
- **Logging**: prefix `[core INFO module]` / `[qgis INFO module]`; per fase een INFO-samenvatting,
  per item DEBUG; log wat NIET gevonden is.
- **Services nemen `log: Optional[Log]` als parameter** en waarschuwen (WARNING) wanneer een
  antwoord leeg of onbruikbaar is; nooit stil een leeg resultaat teruggeven.
- **TDD op de kern**: eerst een falende test in de woorden van de regel, dan de implementatie, dan
  refactor. Figuren en PDF-pagina's worden als PNG bekeken vóór "klaar".
- **Rapporttekst in het Nederlands**, code-identifiers in het Engels; DOV-vaktermen (sondering,
  boring, peilput) blijven Nederlands in identifiers waar dat de koppeling met DOV verduidelijkt.
- **Git**: Conventional Commits, één bestand per commit, `main` is de werkbranch tot v0.1.

## Ontwikkelomgeving

- Kern-tests: gewone Python ≥ 3.9 (`py -3.12 -m venv .venv && .venv\Scripts\pip install -e .[dev]`),
  `pytest tests/core`; live-tests: `pytest -m live`.
- Schil: de Python van een lokale QGIS-installatie (`C:\Program Files\QGIS <versie>\bin\python-qgis*.bat`).
  Headless flow: `scripts/run_headless.py`.
- Plugin laden in QGIS: junction van `desktopstudie/` naar
  `%APPDATA%\QGIS\QGIS3\profiles\default\python\plugins\desktopstudie`, daarna Plugin Reloader.
- Uitvoer van testruns hoort in `uitvoer/` (genegeerd door git).

## Bekende architecturale schuld

Formaat per item: *wat / waarom uitgesteld / wanneer herbekijken*.

- **StudyZone is één ring (geen gaten, geen multipart)** / eenvoud in v1; de schil vlakt een
  geselecteerd feature af tot zijn buitenring / herbekijken zodra een gebruiker een multipolygoon
  of een perceel met een gat aanlevert.
