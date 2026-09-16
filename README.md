# DOV Desktopstudie

**Status:** v0.1 in ontwikkeling. De kern (data, figuren, JSON, `scripts/run_core.py`) is klaar;
de QGIS-schil (dialoog, lagen, PDF) volgt. De installatie-instructies hieronder gelden zodra de
schil er is.

QGIS-plugin die een geotechnische desktopstudie voor een locatie in Vlaanderen automatisch
samenstelt uit open data van [DOV](https://www.dov.vlaanderen.be) en
[geopunt](https://www.geopunt.be). Je geeft een adres, een coördinaat (Lambert 72) of een polygoon
op; de plugin levert een QGIS-project met alle lagen én een PDF-rapport.

## Wat zit in de studie

1. Ligging en topografie: GRB, orthofoto, NGI-topokaart, Digitaal Hoogtemodel Vlaanderen.
2. Historische kaarten: Ferraris, Atlas der Buurtwegen, Vandermaelen, Popp, orthofoto's 1971,
   1979–1990 en 2000–2003.
3. Geologie en bodem: bodemkaart, Quartair- en Tertiairgeologische kaart, HCOV,
   grondwaterkwetsbaarheid, GxG, watertoets, erosie, krimp-zwel, OVAM-uitspraken.
4. Virtuele boring (G3Dv3 en HCOV) op het zwaartepunt van de zone.
5. Bestaand grondonderzoek uit DOV binnen een instelbare straal: sonderingen (met qc-diagram),
   boringen (met lithologie), peilputten (met laatste peil).
6. Geologische doorsnede uit virtuele boringen langs een automatische of zelfgetekende lijn.
7. Samenvatting en aandachtspunten: feiten uit de data met vaste signaleringen.

De plugin rekent niets uit en interpreteert niets zelf. Ze verzamelt, tekent en signaleert.

## Installatie

Vereist QGIS 3.34 of nieuwer (ook QGIS 4.x). Er zijn geen extra Python-packages nodig.

1. Download de laatste `desktopstudie-<versie>.zip` van de releases-pagina.
2. QGIS → Plugins → Plugins beheren en installeren → Installeren uit ZIP.
3. De knop **DOV Desktopstudie** verschijnt in de werkbalk.

## Gebruik

1. Kies de zone: adres, X/Y, polygoon tekenen of een geselecteerd object uit een laag.
2. Stel straal (standaard 500 m), doorsnedelijn en gewenste kaarten in.
3. Vul projectnaam, auteur, bedrijf en logo in en kies een uitvoermap.
4. Start. De plugin haalt alles op, bouwt het QGIS-project en schrijft `rapport.pdf`.

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
`--geen-legendas` om de aparte legendapagina's over te slaan (de profieltekeningen van het Quartair
worden wel opgehaald, die horen bij de inhoud) en `--paginas` om elk blad ook als PNG weg te
schrijven. De uitvoermap krijgt `rapport.pdf`, `studie.qgz`, `data/studie.gpkg`,
`data/studie.json`, `figuren/` en `legendas/`.

Afsluitcodes: 0 = volledig, 2 = geen bruikbare locatie (adres niet gevonden of niets opgegeven),
3 = klaar maar met gaten: een mislukt product of een bron die niet antwoordde. Beide staan in de
samenvatting die het script afdrukt, samen met de duur van de kern en van de schil.

## Bronnen en licenties

Alle data komt van de Vlaamse overheid (Databank Ondergrond Vlaanderen, Digitaal Vlaanderen,
Vlaamse Milieumaatschappij) en het NGI, onder hun eigen gebruiksvoorwaarden (Modellicentie Gratis
Hergebruik en verwante open licenties). Het rapport vermeldt per kaart de bron en het
ophaaltijdstip.

## Ontwikkeling

Zie `CLAUDE.md` voor de architectuur en huisregels en
`docs/superpowers/specs/2026-09-15-dov-desktopstudie-design.md` voor het ontwerp.

```
py -3.12 -m venv .venv
.venv\Scripts\pip install -e .[dev]
pytest tests/core
```

## Licentie

GPL-2.0-or-later. Zie `LICENSE`.
