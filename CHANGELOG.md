# Changelog

Formaat: [Keep a Changelog](https://keepachangelog.com/nl/1.1.0/). Versies volgen SemVer.

## [Unreleased]

Compactere opmaak na de eerste gebruikersronde: minder wit, minder bladen, en de virtuele boring
zegt waar ze genomen is.

### Toegevoegd
- **Kleurschaal onder het hoogtemodel**: de GetLegendGraphic van het DHMV is een kleurbalk over
  heel Vlaanderen. De schil knipt die balk eruit, legt hem op zijn kant en zet hem als strookje
  onder de DTM-kaart, met de uiteinden van de dienst (-50 en 300 mTAW) en de laagste, gemiddelde
  en hoogste hoogte van de zone eronder. Komt de balk niet binnen of ziet de legenda er anders
  uit, dan worden er geen kleuren getekend - een verzonnen schaal hoort niet bij de kaart erboven -
  en zegt de regel eronder waarom. De zone staat op die balk gemarkeerd: een beugel tussen haar
  laagste en hoogste hoogte, of - als die op papier te dicht bij elkaar liggen, wat op een schaal
  van 350 m het gewone geval is - een streepje op het gemiddelde met een aanwijslijn. Zonder die
  markering zegt een balk over heel Vlaanderen niets over een bouwzone van vier meter.
- **Compacte opmaak**: `Settings.compact`, het vinkje "Compacte opmaak (meer op een blad)" op het
  tabblad Instellingen en `--compact` in `run_headless.py`. Uit levert de voorspelbare opmaak:
  hoogstens twee korte stukken per blad. Aan gaat er zoveel op een blad als erop past.
- **Laag "Virtuele boringen"**: elke virtuele boring die de studie nam - die op het representatieve
  punt, per model, en de doorprikpunten langs de doorsnedelijn - als punt met model, X, Y, maaiveld
  en aantal lagen. Paars ruitje, duidelijk anders dan de sonderingen en boringen, gelabeld met het
  model; in het GeoPackage, in de studiegroep en in `studie.qgz`.
- **Hoofdstuk 4 zegt waar de boring genomen is**: een tabel "Plaats van de virtuele boringen" met
  X en Y in Lambert 72 en het maaiveld, per model.
- `PipelineResult.sheets` en de samenvatting van `run_headless.py` noemen het aantal bladen naast
  het aantal rapportpagina's.
- **De grondwaterstanden dragen hun getal en hun legenda.** GHG en GLG hadden een gekleurde kaart
  en verder niets. Ze vragen hun waarde nu op bij de dienst (GetFeatureInfo op het representatieve
  punt: `GHG-waarde_m-mv` 2,85 en `GLG-waarde_m-mv` 3,54 voor Gent, live geverifieerd 2026-09-17)
  en zetten die met de standaardafwijking en het 80 %-betrouwbaarheidsinterval in een tabel onder
  de kaart. De dienst antwoordt in meter ONDER MAAIVELD; de regel eronder rekent dat om naar mTAW
  met het gemeten gemiddelde maaiveld van de zone en noemt die aanname. De kleurbalk van de dienst
  staat er als strookje onder, met haar klassegrenzen (0-1-2-3-4-5-10-15-20 m) erbij: die klassen
  zijn niet even breed, dus wie ze niet uitschrijft leest de helft van de balk als tien meter waar
  ze vijf is. Beide kaarten kregen een leeswijzer die uitlegt wat een gemiddeld hoogste en een
  gemiddeld laagste grondwaterstand zijn.
- **Een dun thema krijgt de basiskaart eronder.** Een kaart die enkele procenten van de uitsnede
  tekent - grondverschuivingen, watertoets, PFAS, OVAM, erosie, dikte van het Quartair - leverde
  een wit blad met een rode cirkel. `MapEntry.backdrop` laat de basiskaart bij dezelfde uitsnede en
  hetzelfde pixelformaat ophalen en tekent het thema erover in het ene beeld dat de pagina
  afdrukt, met de doorzichtigheid die de catalogus voor dat thema kiest. Elke ondergrond is een
  eigen bron; valt ze weg, dan wordt het thema alleen getekend en houdt het blad zijn plaats.

- **Opmerkingen uit de boorbeschrijvingen.** Wat een beschrijving noemt en niet tot de gewone
  grond behoort - een concretie, een zandsteenbank, glauconiet, veen, puin, baksteen, grind,
  keien, een fossielrijke laag - komt als regel onder de boring te staan en als signalering in
  hoofdstuk 7, met de diepte erbij en de zin van de beschrijving zelf geciteerd. De regel werkt
  omgekeerd aan wat je zou verwachten: `core/lithology.ORDINARY` is een lijst van GEWONE woorden
  (de matrix zand/klei/leem/silt, de modificatoren, de kleuren, het Frans van de oude records) en
  alles wat daar niet op staat vlagt. Een onvolledige lijst geeft dus ruis, nooit een gemiste
  vondst. De lijst is gecureerd op 3630 lagen uit 512 boringen rond twaalf punten verspreid over
  Vlaanderen; `scripts/lithology_vocabulary.py` telt ze opnieuw wanneer DOV verandert.
- **De diktekaart van het Quartair werkt weer.** Het zijn contourlijnen, geen vlakken: de
  feitenvraag zocht overlap met de zone en vond nooit iets, en op 1:25 000 lag er geen lijn in
  beeld. De kaart vraagt nu de dichtstbijzijnde lijnen binnen tien kilometer op
  (`MapEntry.fact_within_m`), toont ze met hun afstand, staat op 1:100 000 en zet de dikte die
  G3Dv3 op het representatieve punt geeft erboven - als modelwaarde benoemd. Ligt er geen contour
  in beeld, dan zegt de regel dat en waar de dichtstbijzijnde ligt.

### Gewijzigd
- **De leeswijzer en de "Legenda voor de zone" staan onder hun eigen kaart**, niet meer op bladen
  ernaast: vier regels leeswijzer of twee legenda-regels op een A4 is een blad vol wit. Eerst de
  leeswijzer, dan de legenda. Het kaartkader krimpt met precies wat ze samen nodig hebben en
  nooit verder dan een halve bladhoogte; wat dan nog niet past loopt door op het volgende blad. De uitsnede houdt haar breedte, dus de schaal in het infovak, de schaalbalk
  en het opgehaalde kaartbeeld blijven ongewijzigd. Geldt ook voor de profieltypestrookjes van het
  Quartair; alleen de eenhedentabel van een kaartblad houdt haar eigen blad. Past de leeswijzer
  zelf niet meer onder een leesbare kaart, dan begint het hele blok op het blad erachter.
- **Een kaart zonder kaartbeeld krijgt geen blad meer.** Geen dekking op deze locatie, of een
  ophaling die mislukte: het blad vervalt, en het hoofdstuk Bronnen zegt per kaart wat er gebeurde.
  Per kader, niet per kaart. De legenda voor de zone komt uit de WFS en niet uit het beeld, dus
  die blijft - dan weer op een blad van zichzelf.
- **Een blad vult zich**: een korte tabel, een kleine figuur en de tekst erna komen op hetzelfde
  blad zolang er iets bij past - niet meer tot twee stukken, want een blad met een tabel van vier
  regels erop is nog altijd een blad vol wit. Een blad draagt een hoofdstukkop, dus een stuk uit
  het volgende hoofdstuk begint een nieuw blad; met `compact` mag het mee, met die kop er klein
  bij. Kaartbladen niet: die blijven
  alleen. Een figuur wordt niet langer opgeblazen tot bladbreedte maar hoogstens op ware grootte
  getekend. De voettekst wordt per blad geschreven in plaats van per rapportpagina.
- **De aparte legendapagina's staan standaard UIT.** Het vinkje "Legenda's op aparte pagina's"
  begint leeg, `PluginSettings.legendas` is standaard `False`, en `run_headless.py` heeft
  `--legendas` om ze wel te maken. De profieltypetekeningen van het Quartair komen er hoe dan ook:
  dat is rapportinhoud, geen legendablad.

- **Een elektrische sondering krijgt voorrang op een dichterbije mechanische** bij de keuze welke
  sonderingen een qc-diagram krijgen. Een continu elektrische sondering meet over de volledige
  diepte, een discontinu mechanische met stappen; afstand beslist binnen elke groep. De tabel
  toont nog altijd elke sondering binnen de straal, op afstand gesorteerd, en het hoofdstuk zegt
  waarom een elektrische van 300 m getekend is en een mechanische van 40 m niet.
- **Een uitgeschakelde kaart krijgt geen blad meer** tussen de historische kaarten. Ze staat in
  het hoofdstuk Bronnen, in de tabel "Niet opgenomen kaarten", met de reden erbij. De reden zelf
  is herschreven voor een lezer: de NGI-regel gaf een instructie aan wie de plugin onderhoudt
  ("vul de kaartdienst in"), en dat hoort niet in het rapport van een klant.

### Verouderd
- `--geen-legendas` in `run_headless.py` doet niets meer (de legendapagina's staan al uit) en logt
  een waarschuwing. Het argument blijft bestaan zodat een script uit v0.1 er niet op afbreekt.

## [0.1.0] - 2026-09-16

Eerste release: kern, QGIS-schil en plugin. QGIS 3.34 t/m 4.x, geen extra packages.

### Toegevoegd
- Ontwerp van de plugin (`docs/superpowers/specs/2026-09-15-dov-desktopstudie-design.md`).
- **Kern** (pure Python, geen `qgis`-import): catalogus met één entry per kaart, geometrie in
  Lambert 72, geocoder (geopunt), DOV WFS en XML (sonderingen, boringen, peilputten), virtuele
  boring (doorprik en profielbevraging), WMS GetFeatureInfo en watertoets, signaleringsregels,
  figuren (qc-diagram, lithologiekolom, virtuele boring, doorsnede), rapportboom en orchestrator.
  Elke bron faalt geïsoleerd en wordt als niet-beschikbaar gerapporteerd; parallel ophalen via
  `core/parallel.py`. `scripts/run_core.py` levert data, figuren en JSON zonder QGIS.
- **Kaarten**: ligging (GRB, orthofoto, NGI CartoWeb, DHMV II hillshade en DTM met reliëfstatistiek),
  historisch (Ferraris, Atlas der Buurtwegen, Vandermaelen, Popp, orthofoto's 1971, 1979-1990 en
  2000-2003), geologie en bodem (bodemkaart, Quartair 1/50 000 en 1/200 000, dikte van het Quartair,
  Tertiair, HCOV, grondwaterkwetsbaarheid, GHG en GLG, watertoets pluviaal en fluviaal, erosie,
  krimp-zwel, OVAM, gevoeligheid voor en gekarteerde grondverschuivingen, PFAS-no-regretzones).
  Uitgeschakelde slots voor de historische NGI-reeks en de bommenkaart, die laatste met een vaste
  tekst voor de manuele controle.
- **Doorsnede** uit de profielbevraging: dichte laagkolommen langs de hele lijn, gestapeld op het
  eigen maaiveld van het model, met de doorprik-punten als ankers; sonderingen, boringen en
  peilputten binnen de corridor geprojecteerd.
- **QGIS-schil**: lagen en groepen uit catalogus en datamodel, reliëf uit het DHMV (WCS en zonale
  statistiek), een meerbladige layout uit de rapportboom (staand A4; brede tabellen en figuren
  liggend, kolombreedtes uit de inhoud), WMS-legenda's als afbeelding in bladhoge stroken die nooit
  door een item snijden, per kaart met een code een leeswijzer en een "Legenda voor de zone", de
  profieltypetekeningen van het Quartair van DOV zelf, een dekkingsproef ("geen dekking op deze
  locatie"), export naar PDF (tekst als tekst), bladen als PNG en een zelfstandig `studie.qgz`.
  Pijplijn `run_core` / `prepare` / `finish` met een fasetabel, provenance voor elke bron die de
  schil raadpleegt, GeoPackage en projectbestand vóór de PDF, en afbreken tussen fasen, bladen en
  exportruns zonder halve producten.
- **Plugin**: knop in werkbalk en menu; een niet-modale dialoog met de tabbladen Locatie (adres met
  kandidaten van de geocoder, X/Y in Lambert 72 met buffer, polygoon tekenen op de kaart, eerste
  geselecteerde vlak uit een laag), Instellingen (zoekstraal, aantal figuren, doorsnedelijn
  automatisch/tekenen/uit laag met verlenging, kaartenchecklist, cache, legendapagina's) en Rapport
  (project, projectnummer, auteur, bedrijf, logo, uitvoermap; onthouden in `QgsSettings` onder
  `desktopstudie/`). Kern en HTTP-werk op een `QgsTask`, de rest op de hoofdthread met een
  voortgangsbalk en Annuleren in de berichtenbalk; na afloop zoomt het canvas naar de zone en meldt
  de berichtenbalk het rapport met "Open PDF", mislukte producten en bronnen bij naam, de fasetabel
  in het logpaneel. Per studienaam één groep en één layout "DOV Desktopstudie - <project>" in het
  geopende project, vervangen bij een tweede run met dezelfde naam; uitvoer per run in
  `<uitvoermap>/<project>_<datum>_<tijd>`, de schijfcache gedeeld in `<uitvoermap>/cache`.
- **Scripts**: `run_headless.py` (volledige studie zonder GUI, duur per fase, afsluitcodes 0/2/3),
  `dev_link.cmd` (junction naar een QGIS-profiel), `smoke_plugin.py` (de plugin onbeheerd in een
  echte QGIS, eigen profiel), `build_zip.py` (zip met LICENSE en README.md), `zip_check.py`
  (installatie uit de zip in een schoon profiel), `record_fixtures.py`, `render_figures.py`.
- **CI**: de kern op Python 3.9 en 3.12; de schil in `qgis/qgis:release-3_34` en `qgis/qgis:latest`,
  plus één live studie voor Gent waarvan de bladen als artefact bewaard worden.

### Gewijzigd
- Ten opzichte van het ontwerp: de plugin werkt in het geopende project (geen nieuw project, geen
  vraag); de legendakeuze staat op het tabblad Instellingen; waar een "Legenda voor de zone"
  bestaat, vervangt ze de feitentabel (één tabel per kaart); het hoogtemodel heeft geen legendablad
  maar zegt zijn kleurschaal in de leeswijzer; de profieltypetekeningen zijn rapportinhoud en worden
  ook zonder legendapagina's opgehaald.
- Ten opzichte van het ontwerp: drie geplande bronbestanden zijn er niet gekomen, elk bewust.
  `resources/paginasjabloon.qpt` niet, want de layout wordt in code gebouwd (een .qpt kan geen
  pagina per rapportpagina bijmaken); `resources/stijlen/*.qml` niet, want de huisstijl van elke
  laag staat als `layers.style_*`-helper in code, zodat de memory-laag van een run en dezelfde laag
  uit het GeoPackage gegarandeerd hetzelfde tonen; `dialog.ui` niet, want de dialoog wordt in code
  gebouwd en een .ui zou een tweede plaats zijn waar widgets bestaan.
- Snelheid: de DOV-kaarten vragen hun WMS aan de dienst van hun eigen workspace (enkele kB
  capabilities in plaats van 1,1 MB per kaart), kaartbeelden worden vooraf in één GetMap per blad
  opgehaald en als lokale raster getekend, en de PDF gaat in runs van tien bladen naar de exporter
  met de bladnummers als tekst in de voettekst. Voor Gent (115 bladen, warme cache) ging de schil
  daarmee van 607 s naar 46-48 s (gemeten 2026-09-16); in de plugin 149 s met koude cache.

### Bekende beperkingen
- Geen open WMS voor de historische NGI-reeks (1873-1989); bommenkaart.be is geen open data.
- Geen berekeningen en geen interpretatie: de plugin verzamelt, tekent en signaleert.
- Het DOV-documentportaal antwoordt voor de profieltypetekeningen van het Quartair soms met zijn
  webpagina in plaats van de PNG. Die pagina draagt de directe link naar het bestand; die wordt
  gevolgd en het antwoord dat geen PNG was gaat uit de cache. Blijft ook dat leeg, dan wordt de
  tekening als mislukte bron gemeld.
- Geen `log.txt` in de uitvoermap: de plugin logt naar het logpaneel, het script naar de terminal.
- Een studiezone is één ring: van een multipolygoon telt het grootste deel, gaten vervallen.
- Gecodeerde lithologiecodes (FZ, SI, ...) worden rauw getoond.
- De lagenfase kost in de plugin circa 8 s op de hoofdthread (het lagenpaneel), headless circa 1 s.

[Unreleased]: https://github.com/Vorsie/dov-desktopstudie/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/Vorsie/dov-desktopstudie/releases/tag/v0.1.0
