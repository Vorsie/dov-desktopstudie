# Beveiliging

DOV Desktopstudie is een QGIS-plugin die op jouw computer draait. Ze haalt publieke open data op
bij DOV en geopunt over HTTPS en schrijft bestanden in een map die jij zelf kiest. Er is geen
server, geen account, geen wachtwoord, geen sleutel en geen telemetrie: er gaat niets naar de
onderhouder of naar derden, en er is niets om in te loggen. De enige verbindingen die de plugin
legt, gaan naar de vaste hosts in `desktopstudie/core/catalogue.py` - `services.dov.vlaanderen.be`,
`www.dov.vlaanderen.be`, `geo.api.vlaanderen.be`, `inspirepub.waterinfo.be` en
`cartoweb.wms.ngi.be` - allemaal over HTTPS, met een eigen User-Agent en verder zonder
identificatie.

## Welke versies herstellingen krijgen

Alleen de jongste release - welke dat is, staat op de
[releasepagina](https://github.com/Vorsie/dov-desktopstudie/releases/latest) en in de badge bovenaan
de [README](README.md). Er zijn geen onderhoudstakken voor oudere versies: een herstelling landt op
`main` en komt mee in de eerstvolgende release.

## Een kwetsbaarheid melden

Meld ze **privé**, niet in een openbaar issue:

- via GitHub, op de [beveiligingspagina van de repository](https://github.com/Vorsie/dov-desktopstudie/security):
  *Report a vulnerability* (private vulnerability reporting), of
- per e-mail aan de onderhouder, het adres uit `desktopstudie/metadata.txt`:
  robinvorsselmans1@hotmail.com.

Zet erbij wat je zag, op welke QGIS-versie en met welke invoer; een minimale reproductie helpt
het meest. Reken op een ontvangstbevestiging binnen een week. Dit is een project van één
onderhouder in de vrije tijd: er is geen wachtdienst, geen afgesproken hersteltermijn en geen
beloning. Klopt de melding, dan hoor je wat het plan is en wanneer, en krijg je vermelding in de
release-nota als je dat wil. Publiceer de melding pas nadat de herstelling in een release zit, of
als er na drie maanden niets bewogen is.

## Wat er werkelijk aan oppervlak is

Eerlijker dan "wij nemen beveiliging ernstig": dit is wat een plugin als deze aan te vallen geeft.

- **Ze ontleedt XML en JSON van diensten op afstand.** De DOV-XML gaat door
  `xml.etree.ElementTree`. Een document dat in zijn eerste 1024 bytes een `<!DOCTYPE` draagt wordt
  geweigerd (`core/services/dov_xml._root`): DOV levert nooit een DTD, dus die is op zichzelf al
  verdacht, en daarmee zijn entiteitsexpansie ("billion laughs") en externe entiteiten uitgesloten.
  `ElementTree` haalt zelf geen externe entiteiten op. JSON gaat door `json.loads`. Beeldbestanden
  worden door Qt en matplotlib gedecodeerd; van een PNG die het DOV-documentportaal levert wordt
  eerst gecontroleerd dat het echt een PNG is.
- **Ze schrijft bestanden**, in de uitvoermap die jij kiest, plus een schijfcache ernaast. De
  cache noemt elk antwoord naar de SHA-1 van zijn URL, dus daar komt geen vreemde naam in. Maar
  een **sleutel die een dienst meestuurt** wordt op twee plaatsen wél deel van een bestandsnaam:
  de figuur van een sondering of boring draagt de permkey uit het DOV-antwoord
  (`cpt_<permkey>.png`) en een profieltypetekening haar code. Die worden niet geschoond. Een dienst
  die daar iets anders dan een sleutel in zet, kan dus meesturen waar een PNG belandt - binnen
  jouw rechten. Het staat hier omdat het zo is, niet omdat het ooit gebeurd is: het
  vertrouwensmodel van deze plugin is "wat DOV over HTTPS terugstuurt, is van DOV".
- **Ze draait in QGIS, met jouw rechten.** Een plugin is Python in hetzelfde proces als QGIS; ze
  kan alles wat jij kan. Installeer daarom uit de
  [releases van deze repository](https://github.com/Vorsie/dov-desktopstudie/releases) of uit de
  officiële pluginrepository van QGIS, niet uit een zip die je van iemand anders kreeg.
- **Geen extra packages.** De plugin gebruikt alleen wat QGIS meelevert (`urllib`, numpy,
  matplotlib) en haalt niets binnen tijdens het draaien. De afhankelijkheden in `pyproject.toml`
  zijn er voor de tests en voor de ontwikkelomgeving, niet voor de plugin; `.github/dependabot.yml`
  bewaakt die en de GitHub-actions, meer niet.
- **De gebruiker geeft geen URL's op.** Adres, coördinaat, polygoon, straal: allemaal parameters,
  geen adressen. De enige link die de plugin volgt zonder ze zelf samengesteld te hebben, is de
  directe downloadlink die het DOV-documentportaal in zijn eigen pagina zet voor een
  profieltypetekening.

Geen kwetsbaarheid: een kaart van DOV die volgens jou de verkeerde klasse tekent, een dienst die
plat ligt, of een rapport dat een blad mist. Dat zijn gewone issues - zie
[CONTRIBUTING.md](CONTRIBUTING.md).
