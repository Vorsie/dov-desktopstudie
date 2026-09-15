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
- **Layout-maten altijd via `compat.point_mm`/`size_mm`** (nooit `QgsUnitTypes.LayoutMillimeters`);
  **WMS/WCS-URI's alleen met live geverifieerde laag-, stijl- en formaatnamen** (`gxg:gxg` en
  `pfas:no_regret_zones` zijn stijlen, WCS-formaat is `GeoTIFF`).
- **Tekst in een layout via `QgsTextFormat`, niet via `setFont`.** `QgsLayoutItemLabel.setFont`,
  `QgsLayoutTable.setContentFont` en `setHeaderFont` zijn in 3.34 al `SIP_DEPRECATED` en verdwijnen
  in 4.x; `setTextFormat`/`setContentTextFormat`/`setHeaderTextFormat` blijven. Een `QgsTextFormat`
  draagt zijn eigen grootte: de puntgrootte op de `QFont` kiest alleen het lettertype.
- **`QgsPrintLayout.initializeDefaults()` legt pagina 0 LIGGEND neer.** Het rapport is van kaft tot
  kaft staand A4, dus pagina 0 moet expliciet op `Orientation.Portrait` worden gezet. Gebeurt dat
  niet, dan valt op het titelblad alles onder 210 mm (inhoudsopgave, disclaimer) van het papier -
  zonder enige foutmelding. `tests/qgis/test_layout.py` bewaakt het per pagina.
- **`QgsLayoutItemScaleBar.applyDefaultSize()` overschrijft label en segmentlengte.** Roep het
  eerst aan en zet daarna pas `setUnitLabel`/`setNumberOfSegments`/`setUnitsPerSegment`; omgekeerd
  verdwijnen die instellingen stilzwijgend.
- **WMS-legenda's worden als afbeelding opgehaald** (GetLegendGraphic met `STYLE` en de
  GeoServer-`LEGEND_OPTIONS` uit `MapEntry.legend_options`) en als `QgsLayoutItemPicture`
  geplaatst; `QgsLayoutItemLegend` haalt WMS-legenda's asynchroon op en blijft headless leeg.
  Een legenda die hoger is dan een blad wordt met `QImage.copy()` in bladhoge stroken gesneden,
  nooit tot een onleesbaar postzegeltje geschaald.
- **Een legenda wordt nooit dwars door een legenda-item gesneden.** Een strook die niet op een
  blad past, breekt af op de dichtstbijzijnde volledig witte (of transparante) pixelrij *boven* de
  nominale snede; is er geen enkele witte rij, dan wint het blad. `hcov` en `quartair` hebben
  `legend=False`: hun GetLegendGraphic is een vierkantje van 20x20 zonder klassenaam.
- **Een kaart die openrekt voor haar overlays krijgt een ronde schaal.** Past de zoekstraal niet op
  de catalogusschaal, dan volgt de schaal uit de zoekstraal en leest het infovak "1:6 104"; ze
  wordt naar boven afgerond op de 1-2-5-ladder (`layout.SCALE_STEPS`) en de extent volgt opnieuw
  uit die schaal. Alleen naar boven: naar beneden zou net wegsnijden waarvoor de kaart openrekte.
  De catalogusschaal en `extent_factor` blijven onaangeroerd - dat zijn keuzes, geen tussenstap.
- **Na het bouwen van een layout altijd `layout.refresh()` vóór export**, anders zijn de
  data-gedefinieerde eigenschappen (de legendaschakelaar voorop) nog niet geëvalueerd. Elke
  exportfunctie in `export.py` doet het zelf, zodat geen enkele oproeper het kan vergeten.
  **Paginaindex nooit zelf tellen, altijd `pageCollection().pageCount()`**: een tabel met
  `ExtendToNextPage` maakt zelf pagina's bij, dus een eigen teller loopt achter en de volgende
  rapportpagina belandt bovenop de laatste tabelpagina. Vervolgframes van zo'n tabel beslaan het
  hele blad; trek ze in de contentband terug, anders lopen ze door kop en voettekst.
- **Een tabel krijgt expliciete kolombreedtes; brede tabellen liggen.** QGIS verdeelt de frame-
  breedte gelijk over de kolommen en KAPT af wat niet past - zo verdween de kolom "DOV-fiche" van
  het blad en werd elke uitvoerdersnaam gehalveerd. `layout.column_widths` meet per kolom de
  langste cel (kop als ondergrens, de rest naar rato) en zet die met `setWidth()`; `WrapText`
  breekt de rest binnen de kolom. Wat de kolommen samen mogen krijgen is de framebreedte min
  2 x `cellMargin()` per kolom min `(n+1) x gridStrokeWidth()` - vergeet je die laatste twee, dan
  steekt `totalWidth()` er 2,5 mm overheen. Een tabel van >= 7 kolommen en een figuur dat breder is
  dan hoog krijgen een **liggend** blad; alle maten komen uit `layout._page_metrics(orientation)`.
- **`QgsLayoutExporter` gooit niet, het geeft een code terug.** Een oproeper die de code negeert,
  overhandigt de gebruiker een rapport dat er niet is. Elke export controleert de code en noemt
  ze bij naam via `compat.enum_name` ("FileError", niet "3"). Let op: een oude unscoped C++-enum
  is op PyQt5 een `sip.enumtype` waarvan `dir()` leeg is - de leden staan op de *klasse*
  (`QgsLayoutExporter.Success`); de gemoderniseerde enums (`QgsZonalStatistics.Result`) zijn echte
  Python-enums met `.name`. `enum_name` slikt beide.
- **"The PNG driver does not support update access" is geen fout.** Na het schrijven opent QGIS
  elke PNG opnieuw via GDAL om er een georeferentie aan te hangen; de PNG-driver kent geen
  update-modus en zegt dat per blad op stderr. Het beeld is wel geschreven. `export._quiet_gdal()`
  zet de GDAL-foutafhandelaar stil rond een export; een echte mislukking komt nog steeds terug in
  de ExportResult, die sowieso gecontroleerd wordt.
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
  `LayerNotDefined`. Net zo is `gxg:gxg` de stijl van de twee GxG-lagen `gxg:ghg_mmv_main` (GHG)
  en `gxg:glg_mmv_main` (GLG), elk een eigen catalogusentry (live 2026-09-15).
  Controleer een nieuwe kaartlaag altijd met een echte GetMap, niet met een grep op de
  capabilities. `MapEntry.wms_style` draagt zo'n benoemde stijl; leeg = de laagstandaard.
- **Een WCS vraagt om een dekkingsformaat, geen mimetype.** `format=GeoTIFF` (DescribeCoverage op
  de DHMV-WCS geeft GeoTIFF/HDF/NetCDF) plus `version=1.0.0`; met `image/tiff` komt de laag
  ongeldig terug met "Cannot get test dataset" en zie je dat pas als het reliëf leeg blijft.
- **DOV-eigenaardigheden**: `BBOX` en `CQL_FILTER` nooit samen; paging met startIndex/count (geen
  harde 500-limiet meer waargenomen op 2026-09-15; page_size=500 als veilige default); features
  over pagina's ontdubbelen op id; afkapping door max_features wordt gelogd en in het rapport
  gemeld; CPT qc in MPa, fs/u in kPa, Qt (totale weerstand) in kN; WCS-GetCoverage is multipart.
- **`xml.etree.ElementTree`-valkuil bij DOV-XML.** `Element.iter(tag)` doet exacte tag-matching en
  ondersteunt het `{*}naam`-namespace-jokerteken NIET (dat werkt alleen in de ElementPath-syntax
  van `find`/`findall`/`iterfind`); gebruik dus `root.findall(".//{*}tag")`, nooit
  `root.iter("{*}tag")` — anders levert de parser stilzwijgend een lege lijst op.
- **De pijplijn valt in twee helften uiteen.** `pipeline.run_core` raakt geen QGIS aan (draait dus
  op een werkthread / QgsTask), `pipeline.finish` doet alles wat de hoofdthread vereist: reliëf,
  regels, rapport, lagen, layout, exports. `run_pipeline` is de twee samen voor een oproeper zonder
  threads (het headless script). Beide helften delen één `HttpClient`, dus één schijfcache.
- **Na `relief` draaien de signaleringsregels opnieuw** (`checks.run_all`), want de reliëfregel kan
  pas dan aanslaan. De twee signaleringen die alleen de orchestrator kan kennen - een afgekapte
  WFS-lijst en mislukte doorprik-punten - laten geen spoor in de data na en worden daarom
  meegenomen via `study.orchestrator_signals(result)`. Voeg je zo'n signalering toe, zet de code
  dan in `study.ORCHESTRATOR_CODES` of hij verdwijnt bij die tweede pas.
- **`QgsLayoutManager.addLayout` vernietigt de layout als het weigert.** Het neemt het eigendom
  over; komt er `False` terug (een naam die het al kent), dan is het object weg en geeft de
  volgende aanroep "wrapped C/C++ object has been deleted". Een weigering hoort dus de run te
  stoppen, niet gelogd te worden waarna er verder wordt gewerkt.
- **Volgorde van goedkoop naar duur.** `studie.json` eerst, dan GeoPackage en projectbestand, dan
  pas de layout en de PDF; elk van die drie producten staat onder zijn eigen bewaking, zodat een
  GeoPackage dat nog openstaat in een andere QGIS dat ene product kost en niet de studie
  (`PipelineResult.pdf`, `.geopackage` en `.project_file` zijn `Optional`, `failures` zegt waarom).
  `StudyCancelled` komt door elke bewaking heen - afbreken is geen mislukt product.
- **GeoPackage en projectbestand gaan vóór de PDF de deur uit.** Negentig bladen renderen is de
  langste en meest fragiele stap van een studie; valt ze om, dan moet de gebruiker de data houden
  die al verzameld was. Een mislukte export levert daarom `PipelineResult.pdf = None` plus een
  regel in `failures`, geen exception die de studie weggooit.
- **Elke bron die de schil raadpleegt krijgt provenance.** Het DHMV-reliëf, elke WMS-laag en elke
  legenda worden met `pipeline.record_source` vastgelegd (ok of niet), en daarom draaien de
  signaleringsregels pas ná die fasen: `check_sources` maakt er een signalering van, zodat het
  rapport de ontbrekende kaart noemt in plaats van stil een blad zonder ondergrond af te drukken.
  `record_source` vervangt een bestaande regel met dezelfde bron, zodat een tweede `finish` op
  hetzelfde resultaat geen tegenstrijdige regels oplevert.
- **Het geopende project is niet het product.** De studiegroepen gaan in het project dat de
  gebruiker openheeft; het `.qgz` naast de PDF is een *vers* `QgsProject` uit het GeoPackage
  (`layers.standalone_project`), zodat het bestand weken later op een andere machine nog opengaat.
  De huisstijl van elke laag staat daarom in `layers.style_*`-helpers: één bron voor de memory-laag
  van een run én voor dezelfde laag uit het GeoPackage.
- **Elke bron faalt geïsoleerd - maar een bron die HELEMAAL niets levert is geen leeg antwoord.**
  Een falende service geeft een `Signalering("bron niet beschikbaar")` en een logregel; het rapport
  gaat door. Nooit stil overslaan. Let op het randgeval bij een bron die per punt wordt bevraagd
  (GetFeatureInfo): vallen álle punten weg, dan is de kaart onbereikbaar, niet leeg - `[]` zou als
  "geen eenheden binnen de zone" in het rapport komen en van een platte watertoets-dienst een
  perceel zonder overstromingsrisico maken. Dat geldt ook
  bínnen een fase: `study._Runner._load_each` haalt elk item in een eigen future op, zodat één
  onbereikbare fiche alleen dat item kost (`pool.map` gooit de eerste fout en verliest de rest).
- **Parallel ophalen gaat via `core/parallel.load_each`**: elk item geïsoleerd, mislukkingen
  geteld en gelogd, en bij afbreken `shutdown(wait=False, cancel_futures=True)` - met een `with`
  wacht de pool ook op de ronde die ze net had uitgedeeld, en duurt "stop" twee keer een item.
  Nest je een pool binnen een pool (punten binnen kaarten), zet de binnenste dan op 1-2 werkers:
  anders is de gelijktijdigheid `max_workers²` en gaat de dienst throttelen.
- **Figuren zonder pyplot.** `figures/common.py` levert `new_figure`/`new_figure_grid`: een
  `Figure` met een eigen `FigureCanvasAgg`. `pyplot` parkeert elke figuur in een globale registry
  tot iemand `close()` roept - een lek in een lange QGIS-sessie en een race vanuit een QgsTask.
  Nooit `plt.subplots` in `core/`; `tests/core/test_figures.py` bewaakt het.
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
- Schil: de Python van een lokale QGIS-installatie (`C:\Program Files\QGIS <versie>\bin\python-qgis*.bat`),
  hier QGIS 3.40.15 LTR (Python 3.12, numpy 1.26, matplotlib 3.10). Eenmalig pytest erin zetten
  (alleen voor ontwikkelaars, de plugin heeft het niet nodig):
  `"C:\Program Files\QGIS 3.40.15\bin\python-qgis-ltr.bat" -m pip install --user pytest`.
  Schil-tests: `"C:\Program Files\QGIS 3.40.15\bin\python-qgis-ltr.bat" -m pytest tests/qgis -q`
  (live-tests: `... -m pytest tests/qgis -q -m live`). Zet `QT_QPA_PLATFORM=offscreen` in de shell;
  `tests/qgis/conftest.py` doet het ook zelf en start één `QgsApplication` per sessie (`qgs_app`).
  Vanuit PowerShell: `& "C:\Program Files\QGIS 3.40.15\bin\python-qgis-ltr.bat" -m pytest tests/qgis -q`.
  In de gewone venv wordt `tests/qgis` in zijn geheel overgeslagen (`pytest.importorskip("qgis.core")`
  in de conftest), dus `.venv\Scripts\python -m pytest tests -q` blijft groen zonder QGIS.
- **Offscreen rendert zonder lettertypes: zet `QT_QPA_FONTDIR`.** Het `offscreen`-platform gebruikt
  Qt's eigen lettertypedatabank en die zoekt in `<QGIS>/apps/Qt5/lib/fonts`, een map die niet
  bestaat (`QFontDatabase: Cannot find font directory`). Elke letter komt dan als zwart blokje uit
  de export terwijl de tests groen blijven - de layout klopt, alleen het lettertype ontbreekt. Voor
  een echte export headless dus `QT_QPA_FONTDIR=C:\Windows\Fonts` (Linux-images:
  `/usr/share/fonts`). `compat.ensure_font_dir()` zet hem zelf als hij onder offscreen leeg is en
  logt dat; `pipeline.finish` roept het aan vóór de eerste render. Meetbaar gemaakt in
  `tests/qgis/test_export.py`: van de kopband van een blad is mét lettertypemap 0,6 % puur zwart,
  zonder 20,2 %. Pagina's altijd als PNG bekijken vóór "klaar".
- **Een `QgsProject` in een pytest-fixture crasht bij teardown.** Een project dat een fixture nog
  vasthoudt, wordt tijdens de fixture-afbouw vrijgegeven en dat laat het proces op Windows
  (QGIS 3.40.15) omvallen met een access violation *nadat* elke test al PASSED meldde: groene
  uitvoer, exitcode 0xC0000005. Gebruik de `project`-fixture uit `tests/qgis/conftest.py`, die het
  met `deleteLater()` aan Qt overlaat. Een project dat in de testbody zelf ontstaat en daar sterft,
  is wel veilig.
- **Een layout sterft met zijn items.** `layout.items()` of `pageCollection().itemsOnPage(i)` op
  een tijdelijke layout (`build()...`) geeft wrappers die meteen daarna dood zijn ("wrapped C/C++
  object ... has been deleted"). Hou de layout in een lokale variabele zolang je haar items leest.
  De headless flow (`scripts/run_headless.py`) bestaat nog niet; die komt met taak S6 van het
  schil-plan.
- **Een rapport renderen kost seconden per blad, dus doe het in tests zo weinig mogelijk.** De
  pijplijntests knippen de catalogus terug tot één kaart per hoofdstuk (`offline_shell`) en slaan
  de echte PDF-export over waar die niet de vraag is (`no_pdf`); één volledige run draagt de meeste
  beweringen. Zo blijft `tests/qgis` onder de minuut. Tests die meer dan 20 s duren, dragen
  `@pytest.mark.slow` (geregistreerd in pyproject, standaard wél geselecteerd). De live
  pijplijntest (`-m live -s`) draait de echte studie voor Gent en laat haar uitvoer in
  `uitvoer/pipeline_live2/` staan, juist om de bladen te bekijken.
- Kern end-to-end zonder QGIS: `python scripts/run_core.py --adres "..." --out uitvoer/<naam>`
  (of `--x/--y`, niet allebei); `--straal` zet de zoekstraal, `--buffer` de zonecirkel,
  `--cache use|refresh|off` de schijfcache. Levert `data/studie.json` en `figuren/*.png`, geen
  kaarten en geen PDF. Afsluitcodes: 0 = volledig, 2 = adres niet gevonden, 3 = klaar maar met
  mislukte bronnen.
- Fixtures verversen: `python scripts/record_fixtures.py` (schrijft `tests/core/fixtures/` opnieuw,
  inclusief de bron-URL en datum in de README ernaast).
- Plugin laden in QGIS: junction van `desktopstudie/` naar
  `%APPDATA%\QGIS\QGIS3\profiles\default\python\plugins\desktopstudie`, daarna Plugin Reloader.
- Uitvoer van testruns hoort in `uitvoer/` (genegeerd door git).
- Figuren visueel controleren: `python scripts/render_figures.py` → `uitvoer/figuren_check/`.

## Bekende architecturale schuld

Formaat per item: *wat / waarom uitgesteld / wanneer herbekijken*.

- **StudyZone is één ring (geen gaten, geen multipart)** / eenvoud in v1; de schil vlakt een
  geselecteerd feature af tot zijn buitenring / herbekijken zodra een gebruiker een multipolygoon
  of een perceel met een gat aanlevert.
- **Gecodeerde-lithologiecodes (FZ, SI, SN, ...) worden rauw getoond** / de officiële DOV-codelijst
  is niet als open XSD gevonden / herbekijken zodra een collega de codes in het rapport onleesbaar
  vindt: vertaaltabel in de presentatielaag toevoegen, raw code als tooltip behouden.
- **Geen rapport zonder QGIS** / kaartpagina's en PDF komen uit QGIS-layouts; `run_core.py` levert
  alleen data, figuren en JSON / herbekijken als collega's zonder QGIS de studie willen draaien:
  "lite"-CLI met matplotlib-kaarten via WMS GetMap.
