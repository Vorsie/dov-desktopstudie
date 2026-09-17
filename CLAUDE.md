# DOV Desktopstudie — projectinstructies

QGIS-plugin die uit een adres, coördinaat of polygoon een geotechnische desktopstudie voor
Vlaanderen samenstelt: QGIS-project met lagen + PDF-rapport, uitsluitend uit open data van DOV en
geopunt. Ontwerp: `docs/superpowers/specs/2026-09-15-dov-desktopstudie-design.md` (lees dat eerst).

Onafhankelijk, open-source project (GPL-2.0-or-later). Clean room: kopieer geen code uit andere
lokale projecten; alleen publiek gedocumenteerde service-eigenaardigheden mogen worden hergebruikt.

## Architectuur

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
`desktopstudie/qgis/` is de dunne schil: lagen (`layers.py`), reliëf (`dem.py`), layout
(`layout.py`), export (`export.py`), versieshims (`compat.py`), de pijplijn (`pipeline.py`:
`run_core` / `prepare` / `finish`, `run_pipeline` als alles-in-één) en de plugin zelf - `plugin.py`
(actie en menu), `dialog.py` (het formulier, in code gebouwd), `zone_input.py` (pure functies:
adres, X/Y, getekende ring of geselecteerd object -> `StudyZone` in Lambert 72; doorsnedelijn;
uitvoermap per run), `map_tools.py` (polygoon/lijn tekenen), `task.py` (`StudyTask`, `StudyRunner`,
het logpaneel) en `settings.py` (`QgsSettings`). Kaarten staan uitsluitend in `core/catalogue.py`:
één entry per kaart; een kaart toevoegen = één entry, geen code.

**De stroom van Start tot rapport, in de plugin.** De dialoog leest haar widgets tot een
`StudyRequest` (zone, `Settings`, `ReportMeta`, runmap `<uitvoermap>/<project>_<yyyymmdd>_<HHMM>`
uit `zone_input.run_folder`, cachemodus, legendakeuze en `cache_dir=<uitvoermap>/cache`) en geeft
die aan `StudyRunner.start`. De runner zet een voortgangsitem met Annuleren in de berichtenbalk en
start een `StudyTask` (`QgsTask`). Op de **werkthread** draaien `pipeline.run_core` (de kern:
geocoder, WFS/XML, virtuele boring, watertoets, figuren) en `pipeline.prepare` (legenda's,
profieltypetekeningen, kaartbeelden - gepland op `layout.overlay_boxes`, zonder één laag), met één
`HttpClient` en dus één schijfcache; de werker krijgt `QgsTask.isCanceled` als `should_cancel`.
`StudyTask.finished()` draait op de hoofdthread in de slot van de taakbeheerder, die de taak daarna
verwijdert: de uitkomst verlaat de taak als data (`WorkerOutcome`), de taak laat callback en
connecties los, en de runner plant `_assemble` met `QTimer.singleShot(0, ...)` op zichzelf. Daar
bevriest ze het canvas en roept ze `pipeline.finish(project, result, meta, out_dir, prepared=...)`
op de **hoofdthread**: reliëf (WCS + zonale statistiek op de zonelaag, bewust niet in de werker),
lagen (één groep "DOV Desktopstudie - <project>" met de hoofdstukgroepen erin, ingeklapt, alleen
GRB aan), signaleringen + `studie.json` + rapportboom, GeoPackage + `studie.qgz`, de layout
"DOV Desktopstudie - <project>", PDF-export in runs van tien bladen. `finish` pollt `should_cancel`
tussen fasen, vóór elke WMS-laag, tussen bladen van de layout en tussen exportruns; de
`should_cancel` van de runner roept eerst `QCoreApplication.processEvents()` aan, zodat de balk
beweegt en Annuleren gehoord wordt, en een afgebroken export laat geen halve PDF achter. Alles wat
een run in het geopende project achterlaat draagt de studienaam (`pipeline.study_group_name`,
`layout.layout_name`, `REPORT_OVERLAY_FLAG`); een tweede run met dezelfde naam vervangt precies dat
(`layers.add_group(parent=)` vervangt binnen zijn ouder, `drop_previous_run(owner=)` alleen de
layout en kopieën van die naam) en een andere studie in hetzelfde project blijft staan. De plugin
werkt in het geopende project: geen `newProject()`, geen vraag. Aan het einde: canvas vrij en één
keer ververst, zoom naar de zone, succesmelding met "Open PDF", mislukte producten en bronnen bij
naam als waarschuwing, een omgevallen kern als kritieke melding, en `finished(result|None)` zodat
de dialoog Start weer vrijgeeft. Wat de dialoog onthoudt staat onder `desktopstudie/` in
`QgsSettings` (`settings.PluginSettings`): `bedrijf`, `auteur`, `logo`, `straal`, `uitvoermap`,
`cache`, `legendas` (standaard UIT), `compact` (standaard uit). Headless (`scripts/run_headless.py`) roept `run_core` en `finish` zelf aan -
zonder `prepared` doet `finish` eerst `prepare` op de eigen thread - met `study_groups=False` (het
geopende `QgsProject` ziet niemand) en de cache in `<out>/data/cache`.

## Harde regels

- **Geen qgis-import in `core/`.** Bewaakt door `tests/core/test_no_qgis_imports.py`.
- **Schil-tests draaien alleen in QGIS-Python; CI in de containers.** `tests/qgis` importeert
  `qgis.core` en slaat zichzelf in een gewone venv over (`importorskip` in de conftest). Lokaal:
  `python-qgis-ltr.bat -m pytest tests/qgis`; in CI in `qgis/qgis:release-3_34` en
  `qgis/qgis:latest` (`ci-qgis.yml`). Geen stubs of mocks van `qgis.core` in de venv: een
  4.x-API-breuk hoort in een echte QGIS zichtbaar te worden, niet in een namaak.
- **Compatibel met QGIS 3.34 t/m 4.x.** `qgisMinimumVersion=3.34`, `supportsQt6=True`. Alleen
  API's die in 3.34 bestaan. Imports via `qgis.PyQt`. Qt-enums altijd scoped
  (`Qt.AlignmentFlag.AlignRight`, `QDialog.DialogCode.Accepted`). Python-syntaxis ≥ 3.9: geen
  `match`, geen geneste f-strings, `from __future__ import annotations` in elk bestand. QGIS
  3.34/3.40 op Windows leveren Python 3.12; de 3.9-syntaxisregel blijft als ondergrens en CI test
  ook op 3.9.
- **Drie dingen die alleen in de containers stukgaan, en wat ze betekenen.** De schil-CI draait in
  `qgis/qgis:release-3_34` en `qgis/qgis:latest`; wat daar rood wordt, is niet vanzelf een
  testfout.
  - **3.34 levert oude enums als `sip.enumtype`.** `QgsZonalStatistics.Result` is daar zo'n type:
    `getattr` erop werkt, maar `dir()` geeft alleen de methodes van `int`, dus het type valt niet
    te doorlopen. De leden staan op de klasse eromheen, en `__qualname__`/`__module__` van het type
    wijzen die klasse aan - dat is wat `compat.enum_name` doet. Zonder die omweg leest het
    logpaneel "DHMV zonale statistiek gaf 1". Lokaal na te doen op 3.40 met
    `QgsLayoutExporter.ExportResult`, dat daar nog zo'n type is.
  - **QGIS 4 percent-codeert een provider-URI.** `url=https%3A%2F%2F...`, `styles=gxg%3Agxg`. Een
    test die `"url=https://..." in layer.source()` doet, is daar rood terwijl de laag klopt. Lees
    de URI met `urllib.parse.parse_qs` (`keep_blank_values=True`, anders verdwijnt `styles=`);
    `QgsDataSourceUri` ontleedt een raster-URI met &-scheiding NIET (geverifieerd op 3.40.15).
  - **QGIS 4 zendt `messageReceived(message, tag, level)` niet meer uit.** Het signaal is afgekeurd;
    `QgsMessageLog::emitMessage` doet `messageReceivedWithFormat(message, tag, level, format)` plus
    `messageReceived(bool)`. De plugin merkt daar niets van - die schrijft met
    `QgsMessageLog.logMessage` en het logpaneel luistert in C++ - maar wie in een test zelf
    meeluistert, moet het nieuwe signaal nemen als het bestaat (op 3.34/3.40 bestaat het niet).
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
  nooit tot een onleesbaar postzegeltje geschaald. `legend_options` staat standaard op
  `columns:2;columnheight:1100;fontSize:9;forceLabels:on`: vier kolommen van 7 pt passen op een
  scherm, niet op papier, en zonder `forceLabels` laat GeoServer de klassenaam van een laag met één
  klasse gewoon weg.
- **Een legenda wordt nooit dwars door een legenda-item gesneden.** Een strook die niet op een
  blad past, breekt af op de dichtstbijzijnde volledig witte (of transparante) pixelrij *boven* de
  nominale snede; is er geen enkele witte rij, dan wint het blad. `hcov` en `quartair` hebben
  `legend=False`: hun GetLegendGraphic is een vierkantje van 20x20 zonder klassenaam; `dhmv_dtm`
  ook, want zijn legenda is een kleurbalk van 27x18 mm met twee getallen erop.
- **Een kaart met een code krijgt EEN blad: de kaart, met haar leeswijzer en haar legenda
  eronder.** De `Leeswijzer` (`MapEntry.reading_guide`, drie tot vijf zinnen) zegt hoe die code te
  lezen valt en `Legenda voor de zone` welke klassen er werkelijk voorkomen - ontdubbeld, met de
  kolommen die bij die kaart horen (`report_content.ZONE_LEGEND_COLUMNS`). Allebei reizen ze mee
  OP de kaartpagina (`MapPage.guide`, `MapPage.zone_legend`), in die volgorde: vier regels tekst
  of twee legendaregels kostten elk een A4 vol wit. Een lege legenda zegt of de ZONE leeg was of
  de BRON; dat onderscheid mag nooit vervagen.
- **Het kaartkader krimpt voor wat eronder staat - in de hoogte, nooit in de breedte.**
  `layout.map_height` geeft de kaart alles wat overblijft: onder het kader stond al vier centimeter
  wit, dus een korte legenda kost niets, en verder dan `MAP_MIN_H` (120 mm, ongeveer een halve
  bladhoogte) krimpt het kader nooit - wat dan nog niet past loopt door op het volgende blad.
  `layout.crop_extent` snijdt de uitsnede mee, met dezelfde BREEDTE: de breedte bepaalt de schaal
  in het infovak en de sleutel waaronder `plan_map_images` het beeld ophaalde (die rekent altijd op
  volle hoogte). Wie de breedte aanraakt, verandert de gedrukte schaal en laat het blad zoeken naar
  een beeld dat niemand opgehaald heeft. Het infovak onderaan en de schaalbalk hangen aan de VOET
  van het kader (`INFO_BOTTOM_LIFT`, `SCALE_BAR_LIFT`), niet aan een vaste y - de schaalbalk hoort
  tegen zijn kaart, niet onder de tekst.
  Een legenda die niet meer past loopt door op het volgende blad; past de EERSTE brok (de
  leeswijzer) er niet eens onder een kaart op de ondergrens, dan houdt het kader zijn volle hoogte
  en begint het hele blok op het blad erachter (`UnderMap.minimum`). Een halve alinea onder de
  kaart en de andere helft overpagina leest slechter dan een blok dat op een eigen blad begint.
- **De kleurschaal van het hoogtemodel is rapportinhoud, geen legendablad.** De GetLegendGraphic
  van `dhmv_dtm` is een kleurbalk van 16 x 48 px met de titel erboven en "300 - -50" ernaast (live
  2026-09-17, 102 x 68 px). `layout.ramp_rect` zoekt de balk als de langste reeks rijen die met een
  effen kleurloop tegen de linkerrand beginnen, `ramp_strip` knipt die eruit en draait ze een
  kwartslag rechtsom (laag links, hoog rechts), en de kaartpagina tekent ze onder het kader met de
  twee uiteinden uit `catalogue.DHMV_RAMP_MTAW` en de drie hoogtes uit `StudyResult.relief`. Vindt
  `ramp_rect` geen balk, dan komt er GEEN strook: een kleurschaal die niet bij de kaart erboven
  hoort is erger dan geen kleurschaal, en de regel eronder zegt waarom.
  **En de zone staat er zelf op gemarkeerd**, anders zegt een balk van -50 tot 300 mTAW over een
  bouwzone van vier meter niets: alles is een tint. De kern rekent de plaatsen uit als breuk van
  de strook (`ColourRamp.band`, `mean_at`; geklemd op 0..1, want een markering naast het papier
  wijst nergens naar), de schil kiest - een beugel tussen laagste en hoogste zodra die op papier
  `RAMP_SPAN_MIN_MM` uit elkaar liggen, anders EEN streepje op het gemiddelde met een aanwijslijn,
  want twee streepjes van een halve millimeter uit elkaar zijn een dik streepje. Zonder gemeten
  reliëf, of zonder strook, wordt er niets gemarkeerd.
  **Niet elke balk is lineair.** De GxG-balk is een reeks klassen van ONGELIJKE breedte die op
  gelijke hoogte getekend worden (grenzen 0-1-2-3-4-5-10-15-20 m, live gelezen 2026-09-17 uit de
  GetLegendGraphic zelf: negen labels op gelijke afstand). Daarom draagt `ColourRamp.ticks` die
  grenzen en wordt er op zo'n balk NOOIT een waarde geïnterpoleerd - het getal staat in de tabel
  erboven. `MapEntry.ramp_low_at_top` zegt aan welke kant de kleinste waarde staat, zodat beide
  balken op papier van klein links naar groot rechts lopen; `ramp_rect` zoekt de balk niet in
  kolom nul maar bij de eerste kleur van elke rij, want de GxG-legenda laat een witte pixel tegen
  de rand.
- **Een kaart zonder kaartbeeld krijgt geen blad.** `prepare` weet het al - de beelden worden
  opgehaald vóór de rapportboom voor het drukwerk gebouwd wordt - en geeft die kennis door als
  `Prepared.unavailable` (`report_content.map_page_key`s, dus per KADER) aan `build_report`, dat
  die bladen weglaat. Het hoofdstuk Bronnen zegt per kaart wat er gebeurde ("geen dekking op deze
  locatie" of de mislukking); dat is waar een lezer dat zoekt, niet op een blad met een leeg kader.
  De legenda voor de zone komt uit de WFS en niet uit het beeld, dus die overleeft het wegvallen -
  dan weer op een blad van zichzelf.
- **Een blad vult zich.** `LayoutBuilder._start` zet een tabel, een figuur of een tekst op het blad
  dat al open staat zolang het past - niet tot een aantal, want een blad met een tabel van vier
  regels erop is een blad vol wit. Eén hoofdstukkop per blad: een stuk uit het volgende hoofdstuk
  begint een nieuw blad, tenzij `compact`, en dan staat de nieuwe kop er klein bij
  (`PACKED_CHAPTER_H`) - een tabel van hoofdstuk 4 onder "3. Geologie en bodem" wordt gelezen als
  hoofdstuk 3. Een kaartblad doet niet mee en vult zijn blad (`_seal`), een staand stuk belandt
  nooit op een liggend blad, en de voettekst wordt PER BLAD geschreven (`_footer_every_sheet`, aan
  het einde van `build`) in plaats van per rapportpagina - twee voetteksten op een blad zijn twee
  paginanummers op een vel papier.
- **Een dun thema wordt over de basiskaart getekend.** `MapEntry.backdrop` markeert de kaarten die
  maar enkele procenten van hun uitsnede tekenen (gemeten op Gent, 2026-09-17: gekarteerde
  grondverschuivingen, erosie, watertoets fluviaal en de dikte van het Quartair 100 % doorzichtig,
  watertoets pluviaal 91 %, OVAM 69 %, PFAS 61 % - tegen 0 % voor de bodemkaart, het Tertiair,
  HCOV en de kwetsbaarheidskaart). `prepare_map_images` haalt daarvoor `catalogue.BASE_MAP_ID` op
  bij dezelfde extent en hetzelfde pixelformaat en schildert het thema erover met de opaciteit uit
  de catalogus, zodat de pagina één beeld tekent en niets achteraf hoeft te passen. De dekkingsproef
  (`_is_empty`) wordt op het THEMA gedaan, vóór er iets onder komt te staan - anders beantwoordt de
  basiskaart de vraag of de dienst hier iets tekent. `TRANSPARENT=TRUE` ging altijd al mee en wordt
  gehonoreerd (live 2026-09-17: mét de parameter vier kanalen met een echt alfa, zonder drie
  kanalen met wit); het lege blad kwam dus niet van een ondoorzichtig thema maar van niets eronder.
  Een ondergrond die mislukt kost het thema zijn achtergrond, nooit zijn blad, en krijgt een eigen
  bronregel (`pipeline._record_backdrops`).
- **De legenda van het Quartair is een tekening, en die tekening bestaat uit twee delen.** Bovenaan
  staat het profieltype zelf (kleurvlak, lettercode, een regel omschrijving), daaronder de
  eenhedentabel van het hele kaartblad - voor elk profieltype van dat blad dezelfde. De schil snijdt
  de kop eraf (`layout.crop_profile_header`: eerste volledig witte rij onder rij 60, anders 110),
  snijdt diezelfde rij van boven van de eenhedentabel (`crop_sheet_units`, anders leest die tabel
  als die van het ene profieltype waarmee ze binnenkwam) en levert `profieltype:<code>` en
  `kaartblad:<nn>` aan `build_report(..., zone_legend_images=...)`. Het blok is **twee bladen**: de
  kaartpagina, met onder het kader per profieltype de regel "Profieltype <code> - kaartblad <nn>"
  en de strook eronder (ware grootte, hoogstens een vijfde van de band, vervolgblad zodra het niet
  meer past), en de eenhedentabel van het kaartblad - die laatste is een tekening van een halve A4
  en houdt daarom haar eigen blad. Geen URL op papier - 145 tekens downloadlink zeggen
  een lezer niets - maar `LegendEntry` houdt code en kaartblad als data, dus de feiten blijven
  machineleesbaar. Een tekening die niet binnenkwam laat de regel staan met "tekening niet
  opgehaald".
- **De legenda-URL van een profieltype is een downloadlink van een documentportaal.** Ze eindigt op
  `_png` maar geeft met HTTP 200 ook wel eens de webpagina van dat portaal terug. Wat
  `layout._drawing_bytes` daarmee doet, en waar de grens ligt, staat één keer beschreven: zie
  **Van de DSpace-omweg zit alleen de goedkoopste stap in de code** in de schuldlijst hieronder.
- **Kaartbeelden worden vooraf opgehaald, niet tijdens het renderen.** De QGIS-WMS-provider haalt
  tegel na tegel op TERWIJL een blad tekent, en het rapport wacht daarop: dat was 312 s van de
  607 s die een studie voor Gent kostte (gemeten 2026-09-16 met de fasetabel). `layout.
  plan_map_images` leidt uit de rapportboom af welke uitsnedes nodig zijn - één per (kaart, kader),
  dus vier GRB-bladen delen wat ze kunnen delen - en `prepare_map_images` haalt ze met acht
  werkers op als één GetMap per blad, op de pixelmaat waarop het blad ze afdrukt (`MAP_IMAGE_DPI`
  = de export-dpi, geplafonneerd op 4096 px). Ze landen als PNG + wereldbestand in
  `data/kaarten/` en de layout tekent die lokale rasters (`layers.snapshot_layer`, CRS expliciet
  gezet - een PNG zegt niet waar hij ligt). De live WMS-lagen blijven voor het QGIS-project; de
  layout raakt ze niet meer aan. Elk kaartbeeld is een eigen bron; loopt één kader van een kaart
  mis, dan is die bron mislukt (`pipeline._fetch_map_images` schrijft één regel per kaart, want
  `record_source` vervangt op naam en een geslaagd kader zou een mislukt kader overschrijven).
- **Een WMS-laag bouwen kost een GetCapabilities, en de DOV-kaarten vragen die aan hun eigen
  workspace.** De globale DOV-dienst (`/geoserver/wms`) antwoordt met heel DOV: 1,1 MB die QGIS in
  2,6 s per kaart parst, vijftien keer per studie, en `clone()` doet het nog eens. Qt's schijfcache
  helpt niet (DOV antwoordt `Cache-Control: max-age=0, must-revalidate`; gemeten 2026-09-16: met
  `setupDefaultProxyAndCache()` 2,6-2,9 s, zonder 2,2-2,9 s). De workspace-dienst
  (`DOV_WORKSPACE_WMS_URL`, `/geoserver/<workspace>/wms`) antwoordt met enkele kB: 0,03 s per kaart,
  en levert byte-identieke GetMap- en GetLegendGraphic-antwoorden (live 2026-09-16, alle vijftien).
  Daar heet een laag bij haar kale naam (`bodemtypes`, niet `bodemkaart:bodemtypes`; met prefix is
  de laag ongeldig), de WFS-typenamen houden hun prefix. `catalogue.dov_wms(layer)` doet de
  vertaling. `finish(study_groups=False)` (headless) bouwt de lagen één keer; de `clone()` voor het
  projectbestand in de plugin kost nu ~1 s en is bewust gelaten.
- **Een dienst die hier niets tekent, zegt dat - en dat kost geen extra oproep.** De Popp-kaart is
  in Gent een wit blad: het mozaiek heeft geen kaartblad voor de stad, en de dienst antwoordt netjes
  met een lege tegel. Het kaartbeeld is er toch al, dus het antwoord valt er gratis uit te lezen:
  `layout._is_empty` in `prepare_map_images` kijkt of alle pixels gelijk of volledig doorzichtig
  zijn. De aparte dekkingsproef (een GetMap van 64 px) bestaat niet meer. Is de tegel leeg, dan
  VERVALT het blad (zie de regel over een kaart zonder kaartbeeld hierboven) en blijft de bron `ok`
  met de reden "geen dekking op deze locatie" (de bronnentabel drukt die reden af achter "ok").
  Twee grenzen. Alleen kaarten
  **zonder feiten**, want een doorzichtige tegel van de watertoets betekent "geen
  overstromingsgevoelig gebied", niet "geen dekking" (live gemeten 2026-09-16). En per **kader**,
  niet per kaart: `no_coverage` draagt `map_image_key`s, zodat een leeg kader de andere bladen van
  dezelfde kaart niet meeneemt. Een ophaling die faalt, verandert niets: onbekend is geen "geen
  dekking".
- **De kaartenkeuze reist mee met het resultaat, en iedereen filtert ermee.** Wat de gebruiker in
  de checklist aanvinkt staat als `Settings.map_ids` in de aanvraag en wordt door `study.run` op
  `StudyResult.map_ids` gezet (None = alle ingeschakelde entries), zodat het ook in `studie.json`
  belandt: een lezer moet kunnen zien welke kaarten een studie NIET bekeken heeft. Elke plek die
  de catalogus voor één studie doorloopt geeft dat door als `catalogue.entries(..., only=...)`:
  de kaartpagina's, de leeswijzers en de zonelegenda's (`report_content`), de bronnentabel, de
  WMS-lagen in het project, de legenda's en `layers.standalone_project`. De kaartbeelden volgen
  gratis, want `plan_map_images` leest de rapportboom. Een uitgevinkte kaart kost dus geen laag,
  geen oproep en geen blad - zonder dat filter drukte haar blad "Bron niet beschikbaar" af, precies
  de zin die een dienst krijgt die plat ligt. Uitzondering: het overzichtsblad van hoofdstuk 5
  tekent op `grb` omdat het de proefpunten toont, ook als GRB zelf niet gekozen is.
- **Eén tabel per kaart.** Waar een `Legenda voor de zone` bestaat, vervangt ze de feitentabel -
  twee tabellen met dezelfde rij zijn er een te veel. Wat alleen de feitentabel had, verhuist mee
  (de gegeneraliseerde legende van de bodemkaart) of verdwijnt bewust (codes die hun eigen naam
  herhalen). `MapFact.rows` in `studie.json` blijven ongemoeid.
- **Een kaart die openrekt voor haar overlays krijgt een ronde schaal.** Past de zoekstraal niet op
  de catalogusschaal, dan volgt de schaal uit de zoekstraal en leest het infovak "1:6 104"; ze
  wordt naar boven afgerond op de 1-2-5-ladder (`layout.SCALE_STEPS`) en de extent volgt opnieuw
  uit die schaal. Alleen naar boven: naar beneden zou net wegsnijden waarvoor de kaart openrekte.
  De catalogusschaal en `extent_factor` blijven onaangeroerd - dat zijn keuzes, geen tussenstap.
- **`QgsLayoutTable.totalSize()` liegt over de hoogte; `rowsVisible` niet.** `totalSize()` geeft
  nooit minder dan het frame dat de tabel kreeg terug (gemeten op 3.40.15: twee rijen in een
  bladhoog frame melden een bladhoogte), dus een tabel valt er niet mee op te meten.
  `rowsVisible(context, hoogte, 0, True, False)` antwoordt wel eerlijk hoeveel rijen er in een
  hoogte passen; `LayoutBuilder._table_height` halveert het interval tot de kortste hoogte die alle
  rijen houdt. De rendercontext komt uit `QgsLayoutUtils.createRenderContextForLayout(layout, None)`.
- **Vóór een export de data-gedefinieerde eigenschappen evalueren** (`export.refresh_data_defined`),
  anders is de legendaschakelaar nog niet geëvalueerd. Elke exportfunctie in `export.py` doet het
  zelf, zodat geen enkele oproeper het kan vergeten. NIET `layout.refresh()`: die herberekent elk
  label (expressiecontext, ellipsoïde-lookup) à 4 ms - 451 labels in Gent, 3,5 s per oproep, en dat
  twee keer per studie. Let op: vanuit Python geeft `page.excludeFromExports()` alleen de vaste
  vlag terug, nooit het oordeel van de regel; wie dat oordeel nodig heeft, evalueert de
  `QgsProperty` zelf (`_frozen_exclusions`). En `dataDefinedProperties().property(k)` is een
  verwijzing in de opslag van de collectie: kopieer ze (`QgsProperty(...)`) vóór een `setProperty`
  op dezelfde sleutel, anders leest de kopie vrijgegeven geheugen (access violation, 3.40.15).
  **Paginaindex nooit zelf tellen, altijd `pageCollection().pageCount()`**: een tabel met
  `ExtendToNextPage` maakt zelf pagina's bij, dus een eigen teller loopt achter en de volgende
  rapportpagina belandt bovenop de laatste tabelpagina. Vervolgframes van zo'n tabel beslaan het
  hele blad; trek ze in de contentband terug, anders lopen ze door kop en voettekst.
- **Een tabel krijgt expliciete kolombreedtes; brede tabellen liggen.** Let op de tweede helft van
  die regel bij het testen: past zelfs de ondergrens van alle kolommen samen niet, dan krimpt
  `column_widths` alles evenredig ("smal is beter dan onzichtbaar") en houdt een kolom haar langste
  onbreekbare woord dus NIET meer. Een test die die eerste helft pint, moet haar breedte met
  `_floor_width` meten in plaats van een getal uit de lettertypes van deze machine aannemen - in de
  containers is dezelfde tekst breder en belandt dezelfde tabel in de andere helft. QGIS verdeelt de frame-
  breedte gelijk over de kolommen en KAPT af wat niet past - zo verdween de kolom "DOV-fiche" van
  het blad en werd elke uitvoerdersnaam gehalveerd. `layout.column_widths` meet per kolom de
  langste cel (kop als ondergrens, de rest naar rato) en zet die met `setWidth()`; `WrapText`
  breekt de rest binnen de kolom. Wat de kolommen samen mogen krijgen is de framebreedte min
  2 x `cellMargin()` per kolom min `(n+1) x gridStrokeWidth()` - vergeet je die laatste twee, dan
  steekt `totalWidth()` er 2,5 mm overheen. Een tabel van >= 7 kolommen en een figuur dat breder is
  dan hoog krijgen een **liggend** blad; alle maten komen uit `layout._page_metrics(orientation)`.
- **De fasen van een run worden geklokt** (`pipeline.PhaseClock`): elke fase meldt zich één keer,
  dat sluit meteen de vorige af, en `PipelineResult.timings` plus een INFO-tabel zeggen waar de
  tijd heen ging. De voortgangsbalk van de plugin leest dezelfde indeling. Meten voor je iets
  versnelt: de PDF-export bleek 312 s van de 607 s, de toenmalige aparte dekkingsproef 0,0 s -
  reden om die eruit te halen in plaats van te versnellen.
- **Prestaties: wat domineert en waarom** (Gent, 115 bladen, warme cache, gemeten 2026-09-16; de
  laptop wisselt tot 4x in snelheid, dus alleen runs kort na elkaar vergelijken). Sinds de
  compactere opmaak (2026-09-17) telt diezelfde studie 67 bladen: de legendabladen staan uit
  (13 kaarten, 15 bladen), de zonelegenda's en de leeswijzers staan onder hun kaart, de Popp-kaart
  zonder dekking krijgt geen blad, de uitgeschakelde kaarten staan in de bronnen in plaats van op
  een blad, en een blad vult zich. Gemeten inktdekking over alle bladen: gemiddeld 28 %, dertien
  bladen onder 5 % (was negentien) - wat er nog leeg staat is het titelblad en het laatste stuk
  van een hoofdstuk, dat per definitie geen buur meer heeft.
  - **De PDF-export geef je nooit in één oproep het hele rapport.** Binnen één
    `QgsLayoutExporter`-oproep kost elk blad ~7 µs x (items in de layout) x (bladen die al
    geëxporteerd zijn): kwadratisch, los van wat er op het blad staat. Synthetisch (115 bladen van
    zes labels): 38 s in één oproep, 10 s via de iterator-interface in vier runs, 508 s voor 230
    bladen. Gent betaalde er 65 van zijn 95 s aan. `export_pdf` voert de ene layout daarom in runs
    van `PDF_PAGES_PER_RUN` (10) bladen aan `QgsLayoutExporter.exportToPdf(iterator, ...)`
    (`_PageRuns`): PDF-export 102-120 s -> 28 s. Binnen zo'n run telt `@layout_numpages` alleen
    de run, dus **de voettekst draagt "pagina n / N" als tekst** (`_number_footers`, id
    `FOOTER_ID`), geschreven zodra de layout compleet is. De PNG-export blijft één oproep: die
    groeit nauwelijks (0,49 s/blad bij 30, 0,56 bij 60) en een exporter per blad kost 1,7 s/blad.
  - **Tekst als tekst** (`textRenderFormat = AlwaysText`): selecteerbaar, doorzoekbaar, 13,5 MB in
    plaats van 34 MB, en 6 % sneller. De exportvlaggen `appendGeoreference`/`exportMetadata`
    maken geen verschil (96,0 s tegen 95,5 s) en staan op hun standaard.
  - **Layout bouwen** (13 s -> 7,5 s): `addPage` kost 35 ms per blad omdat de paginacollectie bij
    elke toevoeging alle pagina's herlegt (O(n²), niet te vermijden via de API; undo blokkeren
    scheelt een vijfde), de volledige `refresh()` aan het einde is vervangen door de gerichte, de
    rijen van een tabel gaan er na de opmaak in.
  - **GeoPackage en projectbestand** (44-84 s -> 4,5-5,9 s): de DOV-capabilities, zie de WMS-regel.
  - Per blad, in dezelfde run: kaart 0,48 s, tabel 0,47 s, figuur 0,28 s, tekst 0,24 s.
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
- **`run_core` en `prepare` raken geen QGIS aan - en dat moet zo blijven.** Ze draaien in de plugin
  op de werkthread (zie de stroom hierboven); wie er een laag, een `QgsProject` of een widget in
  zet, laat de plugin crashen zonder traceback. Alles wat de hoofdthread vereist hoort in `finish`.
- **De kaartpagina en het geplande kaartbeeld lezen dezelfde dozen.** `plan_map_images` (werker)
  en `LayoutBuilder` (hoofdthread) moeten op de meter dezelfde extent vinden, anders zoekt het blad
  zijn beeld onder een sleutel die er niet is. Daarom rekenen beide met `overlay_boxes(result)` -
  proefpunten, zoekstraal (zonebbox + straal) en doorsnedelijn uit het resultaat - en nooit met
  `layer.extent()` (de GEOS-buffer van de zoekstraal is in pure Python niet te reproduceren).
  `map_extent` leest een kale bbox precies zoals een laag; `build_layout(overlay_boxes=...)` geeft
  ze door.
- **Elke fase van `finish` pollt `should_cancel`, en een nieuwe fase ook.** Tussen fasen, vóór elke
  WMS-laag, tussen bladen van de layout en tussen exportruns (`export_pdf(should_cancel=,
  progress=)`). Een fase die minuten kan duren en niet pollt, maakt Annuleren een leugen.
- **Een run schrijft in een eigen map, de cache staat ernaast.** `<uitvoermap>/<project>_<yyyymmdd>_
  <HHMM>` (`zone_input.run_folder`), zodat het GeoPackage van de vorige run - misschien nog open in
  deze QGIS - nooit vergrendeld of overschreven is; de schijfcache in `<uitvoermap>/cache`
  (`StudyRequest.cache_dir` -> `make_client(cache_dir=)`), want een cache in de runmap zelf wordt
  nooit twee keer geraakt. Eén fabriek voor die client: `core/services/http.study_client`
  (`pipeline.make_client` is diezelfde functie onder de naam die de schil gewend is), met
  `<out>/data/cache` als standaard uit `cache_dir_for`. Wie er zelf een `HttpClient` naast bouwt,
  bouwt een tweede cache die de cachemodus van de gebruiker niet kent.
- **Lagen in het geopende project: bevroren canvas, alleen de basiskaart aan.** Elke laag die in
  het project landt kan anders een render starten die tegels trekt op de hoofdthread (gemeten:
  3 renders -> 0, lagenfase 11,4 -> 7,9 s); de hoofdstukgroepen landen ingeklapt met alleen
  `BASE_MAP_ID` (GRB) aangevinkt, de andere kaarten staan klaar maar uit.
- **Instellingen: elke lezing valt terug op haar standaard** (een handmatig bewerkt profiel mag de
  dialoog niet onderuit halen) en de opslag van `PluginSettings` is injecteerbaar - tests schrijven
  in een eigen ini, nooit in het profiel.
- **Logregels van de plugin gaan naar het logpaneel** (tab "DOV Desktopstudie") via
  `task.plugin_log`; het niveau volgt het voorvoegsel (`WARNING` geel, `ERROR` rood), DEBUG blijft
  weg. Mislukte producten en bronnen (afsluitcode 3 headless) komen als `pushWarning` bij naam in
  de berichtenbalk, een omgevallen kern als `pushMessage(..., Qgis.MessageLevel.Critical, 0)` (geen
  `pushCritical`: die bestaat niet op `QgsMessageBar`, en 0 laat de melding staan tot de gebruiker
  ze wegklikt), het rapport als succesmelding met "Open PDF".
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
- **De virtuele boringen zijn een laag, en een aparte.** `layers.virtual_boreholes_layer` zet elke
  boring die de studie nam als punt neer: die op het representatieve punt (een per model, dus
  meerdere punten op één coördinaat) en de doorprikpunten langs de doorsnedelijn, met model, x, y,
  maaiveld en aantal lagen. Paars ruitje (`VB_STYLE`), duidelijk anders dan de sondering (blauwe
  cirkel), de boring (rood vierkant) en de peilput (blauwe driehoek): een gemodelleerde kolom mag op
  geen enkele kaart voor een echte proef doorgaan. De laag hoort bij de proeflagen (`GPKG_GROUPS`,
  `INVESTIGATION_GROUP`), staat dus in het GeoPackage én in `studie.qgz`, en `style_by_name` kent
  haar. Ook bij een studie zonder boring blijft ze bestaan en leeg - een laagnaam die er soms niet
  is, meldt `standalone_project` als zoek.
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
- **De woordenlijst zegt wat GEWOON is; al de rest vlagt.** `core/lithology.ORDINARY` is een
  allowlist (de matrix zand/klei/leem/silt, de modificatoren, de kleuren, de boormethode, de
  eenheden en het Frans van de oude records); elk woord dat er niet op staat is per definitie een
  rariteit en komt als opmerking onder de boring en als signalering in hoofdstuk 7. **Die richting
  mag nooit omgedraaid worden**: een onvolledige lijst geeft ruis, een lijst van "interessante"
  woorden geeft een gemiste vondst, en alleen de eerste fout is ongevaarlijk. Gecureerd op 3630
  lagen uit 512 boringen rond twaalf punten over heel Vlaanderen (`scripts/lithology_vocabulary.py`
  telt opnieuw); widen de allowlist uit die frequentietabel, versmal nooit de vlagregel. Vier
  dingen die de data besliste en geen conventie: de helft van de oude beschrijvingen is Frans; een
  gecodeerde laag draagt codes en wordt overgeslagen (de codelijst is bekende schuld); een bank is
  een rariteit en een bijmenging niet (schelpen worden 400+ keer als bijmenging genoemd, nooit als
  "schelpenbank" - de bank draagt een eigen woord); en "geen kalk" meldt geen kalk. Citeren, nooit
  concluderen: wat een term BETEKENT voor de grond staat er niet bij.
  Twee dingen die de vlagregel NIET aanraken maar wel bepalen wat er op papier komt. Een kort
  brokstuk met een punt is een afkorting, geen waarneming: "Num. planulatus" gaf "num" in het
  rapport van een klant, en `ABBREVIATION_MAX` gooit zo'n stomp weg (kort EN midden in de zin, of
  aan het einde van de beschrijving; de materialen uit `ALWAYS_NOTABLE` blijven altijd staan).
  En `FOSSILS` groepeert de soortnamen tot één "fossielen: ..."-regel per diepte, omdat
  stratigrafische merkers zeggen in welke formatie je zit en niet dat je iets hards raakt.
  **Groeperen is presentatie**: `notable_terms` geeft elke term terug, `summarise` vouwt ze
  alleen samen - er verdwijnt niets.
- **Een lijnenlaag wordt niet met overlap bevraagd.** `MapEntry.fact_within_m` zet de feitenvraag
  van INTERSECTS om naar DWITHIN met een straal, en de rijen komen dichtstbij eerst terug met de
  afstand erbij (`catalogue.DISTANCE_FIELD`, door de kern berekend - het staat in geen enkel
  antwoord). De isopachen van het Quartair zijn zo'n laag: contouren over heel Vlaanderen, en een
  INTERSECTS met een zone van 50 m raakt er nooit een (live 2026-09-17 bij Gent: 0 objecten,
  DWITHIN 5 km 0, DWITHIN 8 km 8, dichtstbijzijnde op 5,68 km met dikte 20 m). Zo'n kaart krijgt
  ook haar eigen ruime schaal, anders blijft het blad leeg. En "binnen het kaartbeeld" is het
  kaartblad zelf (`catalogue.MAP_WIDTH_MM` op de schaal van de kaart, gedeeld door twee), nooit een
  vast getal: de kern rekent erover, dus staat de breedte in de catalogus en tekent de schil ermee.
- **Een elektrische sondering gaat voor een dichterbije mechanische** bij de figuurkeuze
  (`study.for_figures`). Het woord staat in `sondeermethode` ("continu elektrisch"), niet in
  `conus`: beide stonden ingevuld op alle 133 Gentse sonderingen en waren het eens (110 mechanisch,
  23 elektrisch, live 2026-09-17), maar `conus` is een toestelcode met een open woordenschat.
- **Geen rapporttekst die zich tot de ontwikkelaar richt.** Een uitgeschakelde catalogusentry
  krijgt geen blad; haar `note` wordt afgedrukt in de tabel "Niet opgenomen kaarten" van het
  hoofdstuk Bronnen en is dus tekst voor de LEZER - waarom de kaart er niet is en waar ze wel te
  vinden is. "Vul wms_url in en zet enabled=True" stond zo in het rapport van een klant; wat een
  onderhouder moet weten hoort in de schuldlijst hieronder.
  `tests/core/test_report_content.test_no_report_text_addresses_the_developer` loopt elke
  rapporttekst af en bewaakt het.
- **Rapporttekst in het Nederlands**, code-identifiers in het Engels; DOV-vaktermen (sondering,
  boring, peilput) blijven Nederlands in identifiers waar dat de koppeling met DOV verduidelijkt.
- **Git**: Conventional Commits, één bestand per commit; werk op een `feat/`-branch per plan,
  `main` draagt de releases (tag `vX.Y.Z`, de zip uit `build_zip.py` als release-asset).

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
- Volledige studie zonder GUI (kern + schil + PDF), met de QGIS-Python:
  `"C:\Program Files\QGIS 3.40.15\bin\python-qgis-ltr.bat" scripts\run_headless.py --x 104326
  --y 192506 --buffer 50 --out uitvoer\gent --paginas` (of `--adres "..."`). Verder
  `--straal/--project/--projectnummer/--auteur/--bedrijf/--logo/--cache/--legendas/--compact`
  (`--legendas` maakt de legendabladen wel - ze staan uit; de quartairtekeningen en de kleurschaal
  van het hoogtemodel worden hoe dan ook opgehaald, want die zijn rapportinhoud. `--geen-legendas`
  uit v0.1 bestaat nog als verouderd alias dat niets doet);
  `--paginas` schrijft elk blad ook als PNG. Het script zet `QT_QPA_PLATFORM=offscreen` zelf en
  roept `compat.ensure_font_dir()` aan **vóór** `QgsApplication([], True)` (GUI-geschikt, want
  lettertypes en SVG lopen door de QApplication). Afsluitcodes: 0 = volledig, 2 = geen bruikbare
  locatie, 3 = klaar met gaten (mislukt product of bron). De samenvatting noemt de duur van de kern
  en van de schil apart.
- Fixtures verversen: `python scripts/record_fixtures.py` (schrijft `tests/core/fixtures/` opnieuw,
  inclusief de bron-URL en datum in de README ernaast).
- Plugin laden in QGIS: `scripts\dev_link.cmd [profiel]` maakt de junction van `desktopstudie/`
  naar `%APPDATA%\QGIS\QGIS3\profiles\<profiel>\python\plugins\desktopstudie` (standaard
  `default`; weigert als er al iets staat), daarna Plugin Reloader. Onbeheerd doorlopen in een
  echte QGIS, in een **eigen profiel** - de run zet de plugin aan en bewaart bedrijf/auteur/
  uitvoermap in het profiel waarin hij draait: `scripts\dev_link.cmd smoke` en dan
  `"C:\Program Files\QGIS 3.40.15\bin\qgis-ltr-bin.exe" --profile smoke --nologo
  --noversioncheck --code scripts\smoke_plugin.py` (adresmodus voor Gent; status in
  `uitvoer/plugin_gent/smoke_status.json` met de fasetabel en het aantal canvas-renders, log
  ernaast; QGIS sluit zichzelf). Zip voor "Installeren uit ZIP": `python scripts/build_zip.py`
  -> `dist/desktopstudie-<versie uit metadata.txt>.zip`, met LICENSE en README.md in het pakket
  (43 bestanden in 0.1.0, geen `__pycache__`, geen tests). Installatie uit die zip in een schoon
  profiel: `qgis-ltr-bin.exe --profile zipcheck --nologo --noversioncheck --code
  <absoluut pad van scripts\zip_check.py>` installeert via `pyplugin_installer.instance().installFromZipFile`, laadt
  de plugin, opent de dialoog één keer en schrijft `uitvoer/zip_check/zip_status.json`
  (`installed`, `loaded`, `version`, `dialog_opened`, `method`, `plugin_path`); het script weigert
  elk profiel dat niet `zipcheck` heet, dus `default` en `smoke` blijven onaangeraakt. De pluginmap
  van een profiel is `<profiel>/python/plugins` (`qgis.utils.HOME_PLUGIN_PATH`; die naam is al
  eens verhuisd, dus het script leidt ze af uit `QgsApplication.qgisSettingsDirPath()`). Drie
  dingen die QGIS onder `--code` doet: `sys.argv` is `['']` (de commandoregel staat in
  `QgsApplication.arguments()`), de werkmap staat op `sys.path` (een QGIS gestart uit de checkout
  importeert anders de checkout in plaats van het profiel; het script haalt die entry er eerst af
  en meldt dat als `removed_from_sys_path`), en een relatief `--code`-pad liep onder Git Bash
  niet (QGIS sloot normaal af zonder één logregel) - geef het absoluut op. Geverifieerd
  2026-09-16: `installFromZipFile` in 4,0 s, plugin geladen uit het profiel, dialoog open.
- **Een exception in een Qt-slot breekt het testproces af (0xC0000409).** Onder pytest staat de
  standaard `sys.excepthook`, en dan roept PyQt bij een onafgevangen exception in een slot `qFatal`
  aan - geen traceback, alleen een dode proces. In QGIS zelf vangt de eigen excepthook het op. Dus:
  elke slot in de plugin vangt zijn fouten en logt ze, en een testdubbel die aan een signaal hangt
  ook. Let op `QgsMessageBar.widgetAdded`: een item dat de balk zelf maakte (`pushMessage`) komt in
  Python als kale `QWidget` aan; `sip.cast(widget, QgsMessageBarItem)` eerst.
- **Een afgeronde QgsTask leeft tot de taakbeheerder hem opruimt.** Wat hij nog vasthoudt (een
  gebonden methode van de runner, en via die de iface met een `QgsMapCanvas`) sterft dan pas - na
  `exitQgis()` is dat een access violation bij het afsluiten van de sessie (0xC0000005 na 166x
  PASSED). `StudyTask.finished()` laat daarom callback en connecties los, en `tests/qgis/test_task.
  _wait_until` spoelt de `DeferredDelete`-events door na het wachten.
- Uitvoer van testruns hoort in `uitvoer/` (genegeerd door git).
- Figuren visueel controleren: `python scripts/render_figures.py` → `uitvoer/figuren_check/`.

## Bekende architecturale schuld

Formaat per item: *wat / waarom uitgesteld / wanneer herbekijken*.

- **Geen DHMV-hoogteprofiel langs de doorsnedelijn** (ontwerp §6) / `dem.py` doet alleen zonale
  statistiek op de zone (min/max/gemiddelde in de tabel Kerngegevens ligging); het maaiveld op de
  doorsnede komt uit het model van de virtuele boring, niet uit het DHMV. Een echt profiel vraagt
  een WCS-uitsnede langs de lijn plus bemonstering per stap, en de doorsnedefiguur was in v0.1 al
  het duurste onderdeel / herbekijken zodra een gebruiker het verschil tussen het modelmaaiveld en
  het gemeten maaiveld op de doorsnede nodig heeft: dan een DHMV-raster over de corridor ophalen en
  als tweede lijn in `section_figure` tekenen.
- **StudyZone is één ring (geen gaten, geen multipart)** / eenvoud in v1; de schil vlakt een
  geselecteerd feature af tot zijn buitenring / herbekijken zodra een gebruiker een multipolygoon
  of een perceel met een gat aanlevert.
- **Gecodeerde-lithologiecodes (FZ, SI, SN, ...) worden rauw getoond** / de officiële DOV-codelijst
  is niet als open XSD gevonden / herbekijken zodra een collega de codes in het rapport onleesbaar
  vindt: vertaaltabel in de presentatielaag toevoegen, raw code als tooltip behouden.
- **Geen rapport zonder QGIS** / kaartpagina's en PDF komen uit QGIS-layouts; `run_core.py` levert
  alleen data, figuren en JSON, `run_headless.py` heeft de QGIS-Python nodig / herbekijken als
  collega's zonder QGIS de studie willen draaien: "lite"-CLI met matplotlib-kaarten uit de
  kaartbeelden die `prepare` toch al ophaalt (PNG + wereldbestand) en een PDF via matplotlib.
- **Geen `log.txt` in de uitvoermap (ontwerp §8), ook headless niet** / de plugin logt naar het
  logpaneel van QGIS en het script naar stdout; een bestand ernaast is nog niet geschreven /
  herbekijken zodra een gebruiker een mislukte studie wil doorsturen zonder QGIS open te hebben:
  `Log`-sink die ook naar `<runmap>/log.txt` schrijft (de `Log` neemt al een `sink`, dus een
  tweede sink is het hele werk).
- **Van de DSpace-omweg zit alleen de goedkoopste stap in de code** (dé beschrijving van het
  profieltype-portaal; de huisregel hierboven verwijst hiernaar) / het DOV-documentportaal
  antwoordt op de `_png`-downloadlink soms met zijn eigen webpagina (HTTP 200, `text/html`; live
  gezien 2026-09-16, dezelfde URL leverde minuten eerder nog de PNG). `layout._drawing_bytes`
  controleert daarom de PNG-magie, gooit een niet-PNG uit de cache (`HttpClient.forget`, want een
  webpagina in de schijfcache bederft elke volgende run), leest met
  `core/services/dov_portal.content_link` de directe bitstream-link uit die pagina - die staat er
  letterlijk in, mét de bestandsnaam, dus dat kost geen extra oproep - en volgt ze; komt ook daar
  geen PNG uit, dan vraagt ze het nog één keer met `cache_mode="refresh"`
  (`ZONE_LEGEND_TRIES` = 2) en meldt ze de tekening daarna als mislukte bron in plaats van een leeg
  kader af te drukken. Live geverifieerd 2026-09-16: de pagina die de smoke-run deed mislukken
  levert langs die weg de juiste tekening (66 412 bytes PNG). De échte DSpace-omweg (zoekopdracht
  `…/server/api/discover/search/objects?query=DOV Quartair 50000 <code>&dsoType=item` -> item-uuid
  -> `/core/items/<uuid>/bundles` -> bitstream -> `/core/bitstreams/<uuid>/content`, live
  geverifieerd 2026-09-16) blijft eruit: drie extra oproepen per profieltype en een koppeling aan
  de REST-vorm van DSpace / herbekijken zodra het portaal ook die link in de pagina niet meer zet,
  of zodra de tekeningen vaker ontbreken dan binnenkomen.
- **De historische NGI-reeks (1873-1989) is een uitgeschakelde catalogusentry** (`ngi_hist`) / het
  NGI biedt er geen open WMS voor, alleen het Cartesius-portaal / herbekijken zodra het NGI een
  WMS publiceert of Cartesius onder een open licentie komt: `wms_url` en `wms_layer` invullen,
  `enabled=True`, en de laagnaam live verifiëren zoals de huisregel vraagt.
- **De bommenkaart is een uitgeschakelde entry met een vaste manuele-controletekst**
  (`bommenkaart`, `report_content`) / bommenkaart.be (Bom-Be BV) is geen open data en heeft geen
  WMS/WFS / herbekijken zodra Bom-Be een dienst of licentie aanbiedt, of zodra een gebruiker met
  eigen toegang een WMS-URL wil opgeven: dan wordt `wms_url` per installatie configureerbaar in
  plaats van een catalogusconstante.
- **De WMS-lagen worden op de hoofdthread gebouwd, circa 8 s per studie** / de lagenfase kost in
  de plugin 7,9 s (koude cache, 2026-09-16) tegen circa 1 s headless: elke laag die in het
  geopende project landt kost werk in het lagenpaneel (legendaknopen, signalen), en de canvas-
  bevriezing haalt daar alleen de renders uit. Verder terugbrengen betekent de `QgsRasterLayer`s
  in de werker construeren of ze in één keer aan de boom hangen; buiten v0.1 gelaten omdat de
  PDF-export nog altijd domineert / herbekijken zodra een studie op warme cache onder de 30 s
  zit en die 8 s de langste fase op de hoofdthread is, of zodra een gebruiker de bevroren GUI in
  die fase opmerkt.
