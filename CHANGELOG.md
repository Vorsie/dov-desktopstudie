# Changelog

Formaat: [Keep a Changelog](https://keepachangelog.com/nl/1.1.0/). Versies volgen SemVer.

## [Unreleased]

### Toegevoegd
- Ontwerp van de plugin (`docs/superpowers/specs/2026-09-15-dov-desktopstudie-design.md`).
- Pure-Python kern: catalogus, geometrie, DOV WFS/XML, virtuele boring, watertoets, signaleringen,
  figuren, rapportinhoud, orchestrator; `scripts/run_core.py` voor een studie zonder QGIS.
- Extra kaarten en signaleringen: gevoeligheid voor grondverschuivingen, gekarteerde
  grondverschuivingen en PFAS-no-regretzones, plus een uitgeschakeld bommenkaart-slot met
  manuele-controletekst (Bommenkaart.be biedt geen open WMS/WFS).
- Doorsnede op basis van de profielbevraging: de dichte laagkolommen langs de hele lijn, gestapeld
  op het eigen maaiveld van het model, met de doorprik-punten als ankers en terugvalvlak.
- Lege of mislukte bronnen (virtuele boring zonder lagen, profielbevraging, doorsnedepunten) worden
  als niet-beschikbaar gerapporteerd en de headless runner eindigt dan met exitcode 3.
- QGIS-schil: lagen en groepen uit de catalogus en het datamodel, reliëf uit het DHMV (WCS),
  een meerbladige layout uit de rapportboom met opgehaalde WMS-legenda's, export naar PDF,
  bladen als PNG en een zelfstandig QGIS-project, en de pijplijn die dat aan elkaar knoopt
  (`pipeline.run_pipeline`). Brede tabellen en brede figuren krijgen een liggend blad met
  kolombreedtes uit hun eigen inhoud; kaartpagina's labelen alleen de proeven met een figuur.
- GeoPackage en projectbestand worden vóór de PDF geschreven, en elke bron die de schil zelf
  raadpleegt (DHMV, WMS-lagen, legenda's) komt in de bronnenlijst - een mislukte export kost
  daardoor het rapport, niet de studie.
- Leesbare legenda's: elke kaart met een code krijgt een "Leeswijzer" van drie tot vijf zinnen
  (`MapEntry.reading_guide`, met de DOV-pagina die de volledige legende draagt) en een "Legenda
  voor de zone" met alleen de klassen die in de zone liggen - die tabel vervangt de feitentabel,
  zodat er één tabel per kaart op papier staat. De legenda van de Quartairkaart is de tekening van
  DOV zelf: de kopstrook per profieltype (kleurvlak, lettercode, omschrijving) op de legendapagina
  en de eenhedentabel van het kaartblad ernaast, één keer per blad.
- De opgehaalde WMS-legenda's staan in twee kolommen van 9 pt met `forceLabels`, leesbaar op
  papier; het hoogtemodel verloor zijn legendablad (een kleurbalk van 27 x 18 mm) en zegt zijn
  kleurschaal nu in de leeswijzer.
- Kaarten worden bevraagd op dekking: een dienst die op deze locatie niets tekent (de Popp-kaart
  heeft geen blad voor Gent) zegt dat op het kaartblad en in de bronnenlijst - "ok", want de
  dienst antwoordde, met de reden erbij - en krijgt geen legendapagina.
- URL's in tabellen worden ingekort tot ze in hun kolom passen (host + laatste stuk), zodat er
  niets meer middenin een woord wordt afgekapt; de rauwe waarden blijven in `studie.json`.
- `scripts/run_headless.py`: een volledige studie zonder QGIS-GUI (project, GeoPackage, PDF,
  optioneel elk blad als PNG), met de duur van kern en schil apart en afsluitcodes 0/2/3.
  `scripts/_cli.py` deelt de locatie-opties met `run_core.py`.
- CI draait de schiltests in `qgis/qgis:release-3_34` en `qgis/qgis:latest`, plus een losse
  live-studie voor Gent waarvan de bladen als artefact bewaard worden.
