# Changelog

Formaat: [Keep a Changelog](https://keepachangelog.com/nl/1.1.0/). Versies volgen SemVer.

## [Unreleased]

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
- Snelheid: de DOV-kaarten vragen hun WMS aan de dienst van hun eigen workspace (enkele kB
  capabilities in plaats van 1,1 MB per kaart), kaartbeelden worden vooraf in één GetMap per blad
  opgehaald en als lokale raster getekend, en de PDF gaat in runs van tien bladen naar de exporter
  met de bladnummers als tekst in de voettekst. Voor Gent (115 bladen, warme cache) ging de schil
  daarmee van 607 s naar 46-48 s (gemeten 2026-09-16); in de plugin 149 s met koude cache.

### Bekende beperkingen
- Geen open WMS voor de historische NGI-reeks (1873-1989); bommenkaart.be is geen open data.
- Geen berekeningen en geen interpretatie: de plugin verzamelt, tekent en signaleert.
- Het DOV-documentportaal antwoordt voor de profieltypetekeningen van het Quartair soms met zijn
  webpagina in plaats van de PNG; de tekening wordt dan als mislukte bron gemeld.
- Geen `log.txt` in de uitvoermap: de plugin logt naar het logpaneel, het script naar de terminal.
- Een studiezone is één ring: van een multipolygoon telt het grootste deel, gaten vervallen.
- Gecodeerde lithologiecodes (FZ, SI, ...) worden rauw getoond.
- De lagenfase kost in de plugin circa 8 s op de hoofdthread (het lagenpaneel), headless circa 1 s.

[Unreleased]: https://github.com/Vorsie/dov-desktopstudie/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/Vorsie/dov-desktopstudie/releases/tag/v0.1.0
