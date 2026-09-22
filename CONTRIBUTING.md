# Bijdragen

Dit is een klein, open project van één onderhouder. Bijdragen zijn welkom, en een goed bugrapport
is er een: de zwaarste fouten die deze plugin gehad heeft, kwamen van iemand die ergens anders
keek dan Gent. Je hoeft geen ervaren open-sourcebijdrager te zijn. Wie met QGIS werkt en de
ondergrond van Vlaanderen kent, ziet vaak sneller dan de code dat een blad niet klopt.

Deze bladzijde legt uit hoe je het project aan de praat krijgt, welke afspraken er gelden, hoe je
de tests draait, hoe je een bug meldt en hoe je een wijziging voorstelt.

## Wat het project wel en niet doet

De plugin **verzamelt, tekent en signaleert**. Ze rekent niets uit en interpreteert niets.
Draagkracht, zettingen, funderingsadvies, een geologische interpretatie van de doorsnede: dat
hoort bij de ingenieur die het rapport leest, niet bij de plugin. De bronnen blijven beperkt tot
de open data van [DOV](https://www.dov.vlaanderen.be) en [geopunt](https://www.geopunt.be) en wat
daarlangs ontsloten is; een commerciële of gesloten bron komt er niet bij.

Voorstellen die daarbuiten vallen worden vriendelijk gesloten - niet omdat het slechte ideeën
zijn, maar omdat ze een ander product zijn. Een voorstel voor een nieuwe **kaart** uit die open
data is daarentegen precies wat hier past.

## Aan de praat krijgen

Je hebt twee Pythons nodig, en dat is geen ongeluk: de kern (`desktopstudie/core/`) is pure
Python en mag geen `qgis` importeren, de schil (`desktopstudie/qgis/`) draait alleen in de Python
van een QGIS-installatie.

### De kern, in een gewone venv

```
git clone https://github.com/Vorsie/dov-desktopstudie.git
cd dov-desktopstudie
py -3.12 -m venv .venv
.venv\Scripts\pip install -e .[dev]
.venv\Scripts\pytest tests -q
.venv\Scripts\ruff check .
```

`tests/qgis` slaat zichzelf in deze venv over (`importorskip` in de conftest), dus dit blijft
groen zonder QGIS. Alleen de kern draaien, zonder QGIS en zonder rapport:

```
.venv\Scripts\python scripts\run_core.py --adres "Kortrijksesteenweg 100 Gent" --out uitvoer\proef
```

Dat levert `data/studie.json` en `figuren/`: de feiten en de figuren, geen kaarten en geen PDF.

### De schil, in de Python van QGIS

QGIS 3.34 of nieuwer. De paden hieronder zijn die van QGIS 3.40.15 LTR op Windows; pas de versie
aan op wat jij geïnstalleerd hebt.

```
"C:\Program Files\QGIS 3.40.15\bin\python-qgis-ltr.bat" -m pip install --user pytest
set QT_QPA_PLATFORM=offscreen
set QT_QPA_FONTDIR=C:\Windows\Fonts
"C:\Program Files\QGIS 3.40.15\bin\python-qgis-ltr.bat" -m pytest tests\qgis -q
```

`QT_QPA_FONTDIR` is geen detail. Het `offscreen`-platform zoekt lettertypes in een map die niet
bestaat; zonder die variabele komt **elke letter als een zwart blokje** uit de export terwijl de
tests groen blijven. Op Linux is het `/usr/share/fonts`. De plugin zet hem zelf goed
(`compat.ensure_font_dir()`), een losse render in je eigen script niet.

Een volledige studie zonder venster, met dezelfde QGIS-Python:

```
"C:\Program Files\QGIS 3.40.15\bin\python-qgis-ltr.bat" scripts\run_headless.py ^
    --adres "Kortrijksesteenweg 100 Gent" --buffer 50 --out uitvoer\gent --paginas
```

`--paginas` schrijft elk blad ook als PNG weg. Bekijk die bladen. Een rapport dat "klaar" meldt,
kan nog altijd een leeg kader of een onleesbare legenda bevatten.

### De plugin uit je checkout laden

```
scripts\dev_link.cmd
```

Dat maakt een junction van `desktopstudie/` naar de pluginmap van je QGIS-profiel `default`
(`scripts\dev_link.cmd smoke` voor een profiel `smoke`). Het script overschrijft niets: staat er
al een map of junction, dan stopt het en zegt dat. QGIS laadt de plugin daarna rechtstreeks uit
je checkout; met de plugin **Plugin Reloader** herlaad je na elke wijziging zonder QGIS te
herstarten.

Onbeheerd één hele studie in een echte QGIS doorlopen, in een eigen profiel:

```
scripts\dev_link.cmd smoke
"C:\Program Files\QGIS 3.40.15\bin\qgis-ltr-bin.exe" --profile smoke --nologo ^
    --noversioncheck --code C:\pad\naar\checkout\scripts\smoke_plugin.py
```

De status komt in `uitvoer/plugin_gent/smoke_status.json`, een log ernaast; QGIS sluit zichzelf.
Geef het pad na `--code` absoluut op - een relatief pad liep onder Git Bash niet.

## De vier testsuites

| suite | waar | commando |
|---|---|---|
| `tests/core` | gewone venv | `.venv\Scripts\pytest tests\core -q` |
| `tests/scripts` | gewone venv | `.venv\Scripts\pytest tests\scripts -q` |
| `tests/qgis` | QGIS-Python of container | `python-qgis-ltr.bat -m pytest tests\qgis -q` |
| live | beide | `pytest -m live` |

`.venv\Scripts\pytest tests -q` draait de eerste twee in één keer en slaat de derde over. De
live-tests raken de echte diensten van DOV en geopunt en staan standaard uit (`addopts` in
`pyproject.toml`); ze horen erbij als je een parser, een laagnaam of een URL aanpast, en ze mogen
falen omdat een dienst plat ligt - dat is geen fout van deze repository.

Dezelfde schil-tests als in CI, in de twee containers waarin CI ze draait - de oudste QGIS die de
plugin claimt, en de nieuwste, waar een 4.x-breuk het eerst zichtbaar wordt:

```
docker run --rm -v "%cd%":/src -w /src -e QT_QPA_PLATFORM=offscreen ^
    -e QT_QPA_FONTDIR=/usr/share/fonts qgis/qgis:release-3_34 ^
    sh -c "python3 -m pip install --break-system-packages pytest; python3 -m pytest tests/qgis -q -m 'not live'"
docker run --rm -v "%cd%":/src -w /src -e QT_QPA_PLATFORM=offscreen ^
    -e QT_QPA_FONTDIR=/usr/share/fonts qgis/qgis:latest ^
    sh -c "python3 -m pip install --break-system-packages pytest; python3 -m pytest tests/qgis -q -m 'not live'"
```

Drie dingen gaan alleen in die containers stuk, en geen van drie is vanzelf een testfout: QGIS
3.34 levert oude enums als `sip.enumtype` (niet te doorlopen met `dir()`), QGIS 4 percent-codeert
een provider-URI (`url=https%3A%2F%2F...`, dus lees zo'n URI met `urllib.parse.parse_qs`), en
QGIS 4 zendt `messageReceived(message, tag, level)` niet meer uit. `CLAUDE.md` beschrijft ze alle
drie.

Bugs zoeken op plaatsen die niemand gekozen heeft:

```
"C:\Program Files\QGIS 3.40.15\bin\python-qgis-ltr.bat" scripts\random_study.py --aantal 3
```

Het prikt willekeurige punten in Vlaanderen, draait er een volledige studie en kijkt het
resultaat daarna zelf na: bijna lege bladen, een kaart die niets tekent, een kaart die wél iets
tekent maar geen feit oplevert. Elke bevinding is een regel met run, plaats en bladnummer, en de
seed staat erbij zodat een reeks exact te herhalen is.

## Afspraken in de code

Deze staan voluit in `CLAUDE.md`; dit zijn de regels die je bij een wijziging echt tegenkomt.

- **Geen `qgis`-import in `desktopstudie/core/`.** De kern is pure Python (stdlib, numpy,
  matplotlib) en wordt buiten QGIS getest. `tests/core/test_no_qgis_imports.py` bewaakt het.
- **QGIS 3.34 tot en met 4.x.** Alleen API's die in 3.34 bestaan, imports via `qgis.PyQt` (nooit
  rechtstreeks `PyQt5`), en Qt-enums altijd scoped: `Qt.AlignmentFlag.AlignRight`,
  `QDialog.DialogCode.Accepted`. Layout-maten via `compat.point_mm` / `compat.size_mm`.
- **Python 3.9-syntaxis.** Geen `match`, geen geneste f-strings, en
  `from __future__ import annotations` bovenaan elk bestand. CI test ook op 3.9.
- **Geen extra packages.** Alleen wat QGIS meelevert: `urllib`, geen `requests`; geen `pydov`,
  geen `pyproj`. Alles rekent in Lambert 72 (EPSG:31370).
- **Bronnen live verifiëren.** Een laagnaam, stijlnaam, veldnaam of URL komt pas in
  `core/catalogue.py` of in een parser nadat je hem tegen de echte dienst gecontroleerd hebt.
  Documentatie en codelijsten zijn niet gezaghebbend: `pfas:no_regret_zones` bleek een stijl en
  geen laag, en een buurfeaturetype met een geruststellende naam is de kaart niet. Fixtures in
  `tests/core/fixtures/` zijn echte, opgeslagen antwoorden, met bron-URL en datum ernaast.
- **TDD, en de test eerst.** Staat er een regel in woorden ("een kaart zonder kaartbeeld krijgt
  geen blad"), dan is het eerstvolgende bestand dat je opent een testbestand, en die test noemt
  en becommentarieert zichzelf in de woorden van die regel - niet in de namen van de
  implementatie. Zie hem falen, maak hem groen, ruim daarna op.
- **Figuren en bladen bekijk je als PNG** voor je "klaar" zegt. Groene tests bewijzen niet dat er
  iets leesbaars uit de printer komt.
- **Eén bestand per commit.** Dat leest terug als een verhaal en niet als een berg.
- **Kopieer niet twee keer.** Staat hetzelfde blok ergens al, haal het bij de tweede kopie naar
  een gedeelde plek; maar abstraheer niet vooruit op één gebruik, en laat varianten die echt
  verschillen apart staan.
- **Nederlands in alles wat de lezer van het rapport ziet, Engels in identifiers.** DOV-vaktermen
  (sondering, boring, peilput) blijven Nederlands in identifiers waar dat de koppeling met DOV
  verduidelijkt. En: geen Python-foutmelding in rapporttekst - een uitzondering met klassenaam
  wordt voor de lezer vertaald door `model.plain_reason`.
- **`ruff check .`** voor je commit (`line-length = 120`, regels `E,F,W,I,UP,B`).

## Commits

[Conventional Commits](https://www.conventionalcommits.org/), onderwerp in het Engels, kleine
letter, gebiedende wijs, geen punt, hoogstens 72 tekens. De scope is `core`, `qgis` of `scripts`,
of geen scope voor documentatie en versiewerk. De types die in de log staan, met echte
voorbeelden eruit:

```
feat(core): let a coarse coverage ask for a coarse query
fix(qgis): move a zone legend whose first row will not fit
test(core): a class map carries the key to its colours
refactor(core): name the shrink-swell class field once
docs: pin the coarse-coverage and plain-language rules
chore: version 0.3.0
```

Een `test(...)`-commit vóór de `fix(...)` of `feat(...)` die hem groen maakt, is in deze log het
normale patroon, en dat is de bedoeling: de test legt de regel vast, de implementatie laat hem
gelden.

## Een bug melden

Open een issue met het formulier **Bug melden**. Het vraagt om een handvol dingen, en ze zijn
geen formaliteit:

- **Wat er gebeurde en wat je verwachtte.** Eén zin elk is genoeg.
- **De coördinaat of het adres van de studie.** Dit is het belangrijkste veld. Een groot deel van
  de fouten in dit project bestond alleen op een bepaalde plek: een kaart die in Gent dekking
  heeft en elders niet, een boring met een vreemd teken in haar naam, een profieltype waarvoor
  DOV geen tekening publiceert, een isopachenblad dat buiten de kartering leeg blijft. Zonder de
  plek kan niemand je fout naspelen; mét de plek staat ze meestal binnen één run vast.
- **QGIS-versie en besturingssysteem.** De plugin draait van 3.34 tot 4.x, en een deel van de
  fouten zit precies in dat verschil.
- **De foutmelding of de regels uit het logpaneel.** *Beeld > Panelen > Logberichten*, tab
  **DOV Desktopstudie**. Plak wat er in die tab staat: de plugin logt daar per fase een
  samenvatting en per mislukte bron een reden.
- **Of er een PDF uitkwam, en hoe die eruitzag.** Een blad met een leeg kader is een andere fout
  dan een studie die halverwege stopt. Een schermafdruk van het blad zegt meer dan een zin.

Is de kaart zelf fout - de klasse die DOV tekent klopt niet met de werkelijkheid - dan is dat een
zaak voor DOV en niet voor deze plugin. Klopt wat het rapport van die kaart máákt niet, dan is
het hier thuis.

## Een wijziging voorstellen

1. **Eerst een issue**, met het formulier *Nieuwe kaart of verbetering*. Dat kost je vijf minuten
   en voorkomt dat je een middag werkt aan iets wat niet past. Gaat het om een nieuwe bron, zet
   de service-URL erbij: elke bron wordt live geverifieerd voor ze in de catalogus komt.
2. **Een branch per wijziging**, genoemd naar wat ze doet: `feat/...` voor nieuw werk, `fix/...`
   voor een herstelling, `chore/...` voor gereedschap, versies en onderhoud. `main` draagt de
   releases.
3. **Werk in kleine commits**, één bestand per commit, met de test vóór de implementatie.
4. **Draai de suites die je raakt**, plus `ruff check .`. Raakte je de schil, draai dan ook
   `tests/qgis`: die draait niet in je gewone venv, en dus ook niet per ongeluk.
5. **Kijk naar het resultaat.** Een studie renderen en de bladen als PNG bekijken is hier geen
   extra; het is de controle die de echte fouten vindt.
6. **Open een pull request** naar `main` en vul het sjabloon in: wat er verandert en waarom,
   welke suites je gedraaid hebt, of je een echte studie bekeken hebt. CI draait `ci` (de kern op
   Python 3.9 en 3.12) en `ci-qgis` (de schil in de twee containers). Een rode CI die niet aan een
   platliggende dienst ligt, is een rode CI.
7. **De onderhouder kijkt na en merget.** Blijft het stil, stuur gerust na een week een duwtje in
   het issue.

### Wanneer CI draait

De minuten van een account zijn eindig, dus draait er niets twee keer.

| wanneer | wat |
|---|---|
| een commit op je branch, met een openstaande pull request | `ci` + de twee containers van `ci-qgis` |
| een nieuwe commit terwijl de vorige run nog bezig is | de vorige wordt afgebroken (`concurrency`) |
| een push op `main` of `dev` | dezelfde twee, tenzij je alleen documentatie raakte |
| elke maandagochtend, en op de knop *Run workflow* | `headless-live`: één volledige studie voor Gent tegen de echte diensten, met de bladen als artefact |

Wat er **niet** gebeurt: een push op een gewone branch draait niets (de pull request dekt hem al),
een tag draait niets (de release-zip komt uit `scripts/build_zip.py`), en `headless-live` draait
niet op je pull request. Die laatste is `continue-on-error` en geen verplichte check - een DOV dat
plat ligt is geen rode repository - maar draai hem wel met de hand vóór een release en na elke
wijziging aan een service-URL, een parser of de catalogus.

`paths-ignore` staat alleen op `push`, niet op `pull_request`: een workflow die een padfilter
overslaat meldt haar checks nooit, en `core (3.9)`, `core (3.12)` en de twee `shell`-jobs zijn
verplichte checks op `main`. Een pull request met alleen documentatie zou dan eeuwig blijven
wachten. `README.md` staat er om dezelfde reden niet in als de andere `.md`-bestanden: hij zit in
de plugin-zip en `tests/scripts/test_build_zip.py` controleert dat.

Een kaart toevoegen is meestal één entry in `core/catalogue.py` en geen regel code elders. Dat is
met opzet zo: moet je er wél code voor schrijven, dan is er iets anders aan de hand en is het
gesprek in het issue de kortste weg.

## Licentie

Wat je bijdraagt valt onder [GPL-2.0-or-later](LICENSE), net als de rest van de repository.
