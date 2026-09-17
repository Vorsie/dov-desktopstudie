# DOV Desktopstudie

**Status:** v0.1.0, eerste release. Kern en QGIS-schil zijn compleet: dialoog, lagen in het
geopende project, PDF-rapport, headless script. De plugin staat als *experimenteel* gemarkeerd
(`metadata.txt`) tot de eerste ronde gebruikersfeedback verwerkt is.

QGIS-plugin die een geotechnische desktopstudie voor een locatie in Vlaanderen automatisch
samenstelt uit open data van [DOV](https://www.dov.vlaanderen.be) en
[geopunt](https://www.geopunt.be). Je geeft een adres, een coördinaat (Lambert 72) of een polygoon
op; de plugin levert een QGIS-project met alle lagen én een PDF-rapport.

## Wat zit in de studie

1. Ligging en topografie: GRB-basiskaart, orthofoto, NGI-topokaart (CartoWeb), Digitaal
   Hoogtemodel Vlaanderen II (hillshade en DTM 1 m) met de reliëfstatistiek van de zone.
2. Historische kaarten: Ferraris, Atlas der Buurtwegen, Vandermaelen, Popp, orthofoto's 1971,
   1979–1990 en 2000–2003.
3. Geologie en bodem: bodemkaart, Quartairgeologische kaart 1/50 000 en 1/200 000, dikte van het
   Quartair, Tertiairgeologische kaart, HCOV, grondwaterkwetsbaarheid, GHG en GLG, watertoets
   (pluviaal en fluviaal), erosie, krimp-zwelgevoelige gronden, OVAM-uitspraken, gevoeligheid voor
   grondverschuivingen en gekarteerde grondverschuivingen, PFAS-no-regretzones.
4. Virtuele boring (G3Dv3 en HCOV) op het representatieve punt van de zone - het punt dat
   gegarandeerd binnen de zone ligt, ook als die een hoefijzervorm heeft. Het rapport drukt
   het zwaartepunt en het representatieve punt allebei af in de tabel Kerngegevens ligging, en
   hoofdstuk 4 zegt per model op welke X/Y en op welk maaiveld de boring genomen is. Elke genomen
   boring - die op het representatieve punt en de doorprikpunten langs de doorsnedelijn - staat
   ook als punt in de laag "Virtuele boringen".
5. Bestaand grondonderzoek uit DOV binnen een instelbare straal: sonderingen (met qc-diagram),
   boringen (met lithologie), peilputten (met laatste peil).
6. Geologische doorsnede uit virtuele boringen langs een automatische of zelfgetekende lijn.
7. Samenvatting en aandachtspunten: feiten uit de data met vaste signaleringen, plus een vaste
   tekst die naar bommenkaart.be verwijst voor de manuele controle op explosieven.
8. Bronnen: elke geraadpleegde dienst met URL, ophaaltijdstip en of ze antwoordde.

Elke kaart met een code krijgt een leeswijzer en een "Legenda voor de zone" met alleen de
klassen die in de zone voorkomen. Allebei staan ze **onder het kaartkader op het kaartblad zelf** -
eerst de leeswijzer, dan de legenda: het kader krimpt met wat ze nodig hebben (nooit verder dan een
halve bladhoogte) en wat dan nog niet past loopt door op het volgende blad. Het hoogtemodel krijgt
op dezelfde plaats de kleurbalk van de dienst zelf, met de zone erop gemarkeerd - een beugel tussen
de laagste en de hoogste hoogte, of een streepje op het gemiddelde als die te dicht bij elkaar
liggen om te tekenen - en de drie waarden eronder. Een kaart waarvan de
dienst hier geen beeld levert krijgt geen blad; ze staat wel in het hoofdstuk Bronnen, met de reden.
De historische NGI-reeks (1873–1989) en de bommenkaart staan in de catalogus maar uitgeschakeld;
zie *Bekende beperkingen*.

De plugin rekent niets uit en interpreteert niets zelf. Ze verzamelt, tekent en signaleert.

## Installatie

Vereist QGIS 3.34 of nieuwer (ook QGIS 4.x). Er zijn geen extra Python-packages nodig: alles
draait op wat QGIS meelevert (numpy, matplotlib, urllib).

1. Download `desktopstudie-<versie>.zip` van de
   [releases-pagina](https://github.com/Vorsie/dov-desktopstudie/releases).
2. QGIS → Plugins → Plugins beheren en installeren → Installeren uit ZIP.
3. De knop **DOV Desktopstudie** verschijnt in de werkbalk en in het menu Plugins.

## Gebruik

De dialoog is niet-modaal (twee invoermodi zijn klikken op de kaart) en heeft drie tabbladen.

### Locatie

Eén van vier modi, gekozen met de keuzerondjes:

- **Adres.** Typ een adres en klik *Zoek* (of Enter). De geocoder van geopunt geeft kandidaten in
  de lijst eronder; de eerste is geselecteerd, een andere kies je door erop te klikken. Een
  kandidaat zonder huisnummer draagt "(niet op huisnummer)". De zone is een cirkel met de
  opgegeven **buffer** (standaard 50 m) rond het punt.
- **X/Y in Lambert 72 (EPSG:31370).** Een coördinaat in meter, dezelfde buffer.
- **Polygoon tekenen op de kaart.** Klik *Tekenen*, klik de hoekpunten op het kaartvenster,
  rechtsklik sluit af. Het label meldt het aantal hoekpunten en de oppervlakte. Het kaartvenster
  mag in elk CRS staan; de zone gaat naar Lambert 72 met de transformaties van het project.
- **Uit laag (eerste geselecteerde vlak).** Kies een vlakkenlaag uit het project en selecteer er
  een object in. Van een multipolygoon telt het grootste deel, van een vlak met gaten alleen de
  buitenring.

### Instellingen

- **Zoekstraal** (standaard 500 m, 50–5000): de straal rond de zone waarbinnen sonderingen,
  boringen en peilputten uit DOV worden opgehaald.
- **Sonderingen met figuur** en **Boringen met figuur** (standaard 5): hoeveel proeven, van dichtbij
  naar veraf, een eigen figuurblad krijgen. De tabellen noemen alle proeven binnen de straal.
- **Doorsnedelijn**: *Automatisch (langste as van de zone)* met een **verlenging** aan beide
  uiteinden (standaard 100 m; alleen actief in deze modus), *Tekenen op de kaart* (begin- en
  eindpunt, rechtsklik sluit af) of *Uit laag (eerste geselecteerde lijn)* uit een lijnenlaag van
  het project (van een multilijn de twee uiteinden van het langste deel).
- **Kaarten**: de hele catalogus als checklist. Een uitgevinkte kaart krijgt geen laag en geen
  blad. Uitgeschakelde kaarten staan grijs, met de reden als tooltip.
- **Cache**: *Schijfcache gebruiken* (standaard), *Opnieuw ophalen (cache verversen)* of *Geen
  cache*. De cache staat in `<uitvoermap>/cache` en wordt door alle runs in die map gedeeld.
- **Legenda's op aparte pagina's**: staat **uit**. Aangevinkt krijgt elke kaart met een legenda
  een legendablad achter haar kaartblad; de klassen die in de zone liggen staan sowieso al onder
  hun eigen kaart. In de layout zelf schakelt de variabele `legendas` die bladen bij het
  exporteren. De profieltypetekeningen van het Quartair komen er altijd, ook uitgevinkt: dat is
  rapportinhoud.
- **Compacte opmaak (meer op een blad)**: staat **uit**. Standaard delen hoogstens twee korte
  stukken (een tabel, een figuur, een leeswijzer) een blad; aangevinkt gaat er zoveel op een blad
  als erop past. Kaartbladen blijven altijd alleen.

### Rapport

Project (standaard "Desktopstudie"; de naam is ook de sleutel van de studie in het project en de
naam van de uitvoermap), projectnummer, auteur, bedrijf, logo (PNG, JPG of SVG voor het titelblad)
en de uitvoermap (standaard `<gebruikersmap>\Documents\Desktopstudies`). Bedrijf, auteur, logo, zoekstraal,
uitvoermap, cache, legendakeuze en compacte opmaak worden onthouden in het QGIS-profiel
(`QgsSettings`, sleutels `desktopstudie/...`).

### Start

De kern (geocoder, DOV WFS en XML, virtuele boring, watertoets, figuren) en al het HTTP-werk van
de schil (legenda's, profieltypetekeningen, kaartbeelden) draaien op een `QgsTask` in de
achtergrond. Daarna doet de hoofdthread wat QGIS daar vereist - reliëf, lagen, GeoPackage,
projectbestand, layout, PDF-export - en geeft ze tussen fasen, bladen en exportruns de hand aan de
GUI. De berichtenbalk toont een voortgangsbalk met de naam van de fase en een knop **Annuleren**,
die binnen seconden stopt, ook tijdens de PDF-export (er blijft dan geen halve PDF achter). Het
voortgangsbericht mag weggeklikt worden; de studie loopt door en het logpaneel (tab "DOV
Desktopstudie") houdt de logregels en de fasetabel bij.

Na afloop zoomt het kaartvenster naar de zone en meldt de berichtenbalk het rapport met een knop
**Open PDF**. Producten die niet geschreven konden worden en bronnen die niet antwoordden, worden
bij naam gemeld; de bronnen staan ook in het hoofdstuk Bronnen van het rapport.

### Uitvoer

Elke run schrijft in een eigen map `<uitvoermap>/<project>_<yyyymmdd>_<HHMM>`:

| pad | inhoud |
|---|---|
| `rapport.pdf` | het rapport, staand A4, tekst selecteerbaar |
| `studie.qgz` | een zelfstandig QGIS-project: de studielagen uit het GeoPackage plus de WMS-kaarten |
| `data/studie.gpkg` | zone, doorsnedelijn, proefpunten en de virtuele boringen |
| `data/studie.json` | alle verzamelde feiten, signaleringen en bronnen, machineleesbaar |
| `data/kaarten/` | de kaartbeelden van het rapport als PNG met wereldbestand |
| `figuren/` | sondering-, boring-, virtuele-boring- en doorsnedefiguren (PNG) |
| `legendas/` | opgehaalde WMS-legenda's, de profieltypetekeningen van het Quartair en de kleurbalk van het hoogtemodel |

De schijfcache staat ernaast in `<uitvoermap>/cache`, gedeeld door alle runs.

In het geopende project landt één groep "DOV Desktopstudie - <project>" met de hoofdstukgroepen
(ingeklapt, alleen de GRB-basiskaart aangevinkt), de zone met doorsnedelijn en het grondonderzoek,
en in de layoutbeheerder de layout "DOV Desktopstudie - <project>". Een tweede run met dezelfde
projectnaam vervangt precies die groep, die layout en de rapportkopieën; een studie onder een
andere naam blijft staan. De plugin maakt geen nieuw project aan en stelt geen vraag.

## Zonder QGIS-GUI

Dezelfde studie draait zonder venster, met de Python van een QGIS-installatie (of in een
QGIS-Docker-image). Handig voor een batch, een server of een controle vanop de commandolijn:

```
"C:\Program Files\QGIS 3.40.15\bin\python-qgis-ltr.bat" scripts\run_headless.py ^
    --adres "Kortrijksesteenweg 100 Gent" --buffer 50 --out uitvoer\gent
python3 scripts/run_headless.py --x 104326 --y 192506 --buffer 50 --out uitvoer/gent --paginas
```

Kies de locatie met `--adres` of met `--x/--y` (Lambert 72). Verder: `--buffer` de straal van de
zonecirkel, `--straal` de zoekstraal voor grondonderzoek, `--project/--projectnummer/--auteur/
--bedrijf/--logo` voor het titelblad, `--cache use|refresh|off` voor de schijfcache,
`--legendas` om de aparte legendapagina's wel te maken (ze staan uit; de profieltekeningen van het
Quartair worden altijd opgehaald, die horen bij de inhoud), `--compact` voor de compacte opmaak en
`--paginas` om elk blad ook als PNG in `paginas/` weg te schrijven. `--geen-legendas` uit v0.1
bestaat nog maar doet niets meer. De uitvoermap krijgt dezelfde inhoud als een run uit de plugin; de cache staat
hier in `<out>/data/cache`. Het script zet `QT_QPA_PLATFORM=offscreen` zelf en zoekt de
lettertypes van het systeem (zie *Ontwikkeling*).

De samenvatting noemt de duur van de kern en van de schil apart en drukt per fase van de schil de
duur af:

| fase | wat |
|---|---|
| Legendas | GetLegendGraphic per kaart |
| Tekeningen van de profieltypes | de Quartair-tekeningen van het DOV-documentportaal |
| Kleurschaal hoogtemodel | de GetLegendGraphic van het DHMV, waar de kleurbalk uit geknipt wordt |
| Kaartbeelden | één GetMap per kaartblad, acht tegelijk |
| Relief uit DHMV | WCS-uitsnede en zonale statistiek op de zone |
| Lagen | de studielagen en de WMS-lagen in het project |
| Signaleringen en rapport | regels, `studie.json`, rapportboom |
| GeoPackage en projectbestand | `data/studie.gpkg` en `studie.qgz` |
| Layout | alle bladen in één `QgsPrintLayout` |
| PDF-export | in runs van tien bladen |
| Pagina's als PNG | alleen met `--paginas` |

Afsluitcodes: 0 = volledig, 2 = geen bruikbare locatie (adres niet gevonden of niets opgegeven),
3 = klaar maar met gaten: een mislukt product of een bron die niet antwoordde. Beide staan in de
samenvatting.

Alleen de kern, zonder QGIS-Python: `python scripts/run_core.py --adres "..." --out uitvoer/<naam>`
levert `data/studie.json` en `figuren/`, geen kaarten en geen PDF; dezelfde afsluitcodes.

## Prestaties

Reken op ongeveer een minuut per studie in de plugin; de eerste run op een locatie duurt langer
omdat elke bron dan echt opgehaald wordt. Dezelfde zone in Gent telde 115 bladen in v0.1.0 en 68
sinds de compactere opmaak (gemeten 2026-09-17): de legendabladen staan uit, de leeswijzers en de
legenda's voor de zone staan onder hun kaart, een kaart zonder dekking krijgt geen blad en korte
stukken delen er een. Gemeten op 2026-09-16 voor diezelfde zone (toen 115 bladen):
in de plugin 149 s met koude cache, waarvan PDF-export 60 s, layout 24 s, lagen 8 s en de
profieltypetekeningen 21 s (het documentportaal van DOV antwoordde traag); headless op een warme
cache 46–48 s voor de schil, waarvan PDF-export 28 s, layout 9 s en GeoPackage plus projectbestand
5 s. De PDF-export domineert: de kosten zitten in de vectorinhoud van de tabellen, niet in de
kaartbeelden, en de export gaat daarom in runs van tien bladen naar de exporter. Kaartbeelden worden
vooraf in één GetMap per blad opgehaald, niet tegel na tegel tijdens het renderen.

## Bekende beperkingen

- **Historische NGI-kaarten (1873–1989)**: het NGI biedt er geen open WMS voor (alleen het
  Cartesius-portaal). De catalogusentry staat klaar maar uit.
- **Bommenkaart**: bommenkaart.be is commercieel en heeft geen WMS/WFS. Het rapport neemt een vaste
  tekst op die naar de manuele controle verwijst; er is geen laag.
- **Geen berekeningen, geen interpretatie.** Draagkracht, zettingen, funderingsadvies: niet in deze
  plugin.
- **Profieltypetekeningen van het Quartair**: het DOV-documentportaal antwoordt op dezelfde URL soms
  met zijn webpagina in plaats van de PNG (HTTP 200). De plugin herkent dat, haalt de directe link
  naar het bestand uit die pagina en volgt die - meestal komt de tekening daar alsnog uit - en
  probeert het anders nog één keer zonder cache. Blijft ze weg, dan staat ze als mislukte bron in
  het hoofdstuk Bronnen en houdt de legenda haar regel met "tekening niet opgehaald".
- **Geen `log.txt` in de uitvoermap.** De plugin logt naar het logpaneel van QGIS, het script naar
  de terminal.
- **Kaarten zonder dekking**: een dienst die op de locatie niets tekent (de Popp-kaart heeft geen
  blad voor Gent) krijgt geen blad in het rapport. Ze staat wel in de bronnenlijst, als
  "ok - geen dekking op deze locatie"; dat is geen fout van de dienst. Een kaart waarvan het beeld
  niet opgehaald raakte verliest haar blad net zo, en staat als mislukte bron in de lijst.
- **Eén ring per zone.** Een multipolygoon wordt tot zijn grootste deel herleid, gaten vervallen.
- **Gecodeerde lithologiecodes** (FZ, SI, SN, ...) staan rauw in de boringstabellen: de officiële
  DOV-codelijst is niet als open bestand beschikbaar, dus er is niets om ze mee te vertalen.
- **De lagenfase kost in de plugin circa 8 s** op de hoofdthread (het lagenpaneel bouwt per laag
  zijn legendaknopen), tegen circa 1 s headless. Het kaartvenster staat in die seconden stil.

## Bronnen en licenties

Alle data komt van de Vlaamse overheid (Databank Ondergrond Vlaanderen, Digitaal Vlaanderen,
Vlaamse Milieumaatschappij, OVAM) en het NGI, onder hun eigen gebruiksvoorwaarden (Modellicentie
Gratis Hergebruik en verwante open licenties; NGI open data voor CartoWeb). Het rapport vermeldt
per kaart de bron en het ophaaltijdstip, en het hoofdstuk Bronnen elke oproep die de studie deed.

## Ontwikkeling

Zie `CLAUDE.md` voor de architectuur en huisregels en
`docs/superpowers/specs/2026-09-15-dov-desktopstudie-design.md` voor het ontwerp.

Kern (pure Python, geen QGIS nodig):

```
py -3.12 -m venv .venv
.venv\Scripts\pip install -e .[dev]
.venv\Scripts\pytest tests -q
.venv\Scripts\ruff check .
```

`tests/qgis` slaat zichzelf over in die venv. De schil-tests draaien alleen in de Python van een
QGIS-installatie, offscreen en met de lettertypes van het systeem (zonder `QT_QPA_FONTDIR` rendert
offscreen elke letter als zwart blokje terwijl de tests groen blijven):

```
set QT_QPA_PLATFORM=offscreen
set QT_QPA_FONTDIR=C:\Windows\Fonts
"C:\Program Files\QGIS 3.40.15\bin\python-qgis-ltr.bat" -m pytest tests\qgis -q
```

(Eenmalig `... python-qgis-ltr.bat -m pip install --user pytest`; de plugin zelf heeft pytest niet
nodig.) De live pijplijntest (`-m live`) draait een echte studie voor Gent.

Plugin uit de checkout laden: `scripts\dev_link.cmd [profiel]` maakt een junction van
`desktopstudie/` naar de pluginmap van dat QGIS-profiel (standaard `default`; weigert als er al
iets staat), daarna herladen met Plugin Reloader. Onbeheerd doorlopen in een echte QGIS, in een
eigen profiel: `scripts\dev_link.cmd smoke` en dan

```
"C:\Program Files\QGIS 3.40.15\bin\qgis-ltr-bin.exe" --profile smoke --nologo --noversioncheck --code scripts\smoke_plugin.py
```

(adresmodus voor Gent; status met fasetabel in `uitvoer/plugin_gent/smoke_status.json`, QGIS sluit
zichzelf). De zip voor "Installeren uit ZIP": `python scripts\build_zip.py` →
`dist/desktopstudie-<versie uit metadata.txt>.zip`, met `LICENSE` en `README.md` in het pakket.
Installatie uit die zip in een schoon profiel: `scripts\zip_check.py` op dezelfde manier met
`--profile zipcheck` (status in `uitvoer/zip_check/zip_status.json`; geef het `--code`-pad absoluut
op, een relatief pad liep onder Git Bash niet).

CI: de kern op Python 3.9 en 3.12 (`ci.yml`), de schil in de containers `qgis/qgis:release-3_34`
en `qgis/qgis:latest` plus één live studie voor Gent waarvan de bladen als artefact bewaard worden
(`ci-qgis.yml`).

## Licentie

GPL-2.0-or-later. Zie `LICENSE`.
