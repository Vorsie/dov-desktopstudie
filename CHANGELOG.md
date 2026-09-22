# Changelog

Formaat: [Keep a Changelog](https://keepachangelog.com/nl/1.1.0/). Versies volgen SemVer.

## [0.4.1] - 2026-09-22

### Opgelost
- **Enter in de adreslijst koos het adres niet.** De kandidatenlijst had niets aangekoppeld en Enter
  in het adresveld zocht altijd opnieuw. Bovendien reisde de toets door naar de dialoog, die haar
  standaardknop indrukte: een Enter op een kandidaat koos het adres en stelde de geocoder dezelfde
  vraag nog eens. Enter en dubbelklik nemen nu een kandidaat aan, de pijltjes lopen door de lijst,
  en een tweede Enter start de studie.
- **Een hapering bij een kaartdienst kostte een blad.** Kaartbeelden en ondergronden krijgen drie
  pogingen in plaats van twee; legendes en tekeningen blijven zoals ze waren en de time-out blijft
  30 s.
- **Een ontbrekend kaartbeeld stond als aandachtspunt tussen de bevindingen over de ondergrond.**
  Die melding gaat over het rapport, niet over de grond, en draagt nu `info`.
- **Het infovak op een kaartblad liep over zijn rand.** De breedte was de eigen meting van de
  langste regel, zonder marge, zodat de tekenaar met zijn eigen metriek een extra regel op de rand
  zette. De reserve is gemeten (drie keer 4,8 % van de breedte) en is nu een aandeel in plaats van
  een vaste millimeter, wat op QGIS 3.34 wél houdt en op 1 mm niet.

## [0.4.0] - 2026-09-22

### Gewijzigd
- **De Franse beschrijvingen worden geklasseerd zoals de Nederlandse.** Een kwart van de gemeten
  lagen (874 van 3630) staat in het Frans - de oude records vooral - en daar vlagden 615 van de
  893 woorden, tegen 140 nu. De kleuren en alles wat erop gebouwd is, schelpen en plantenresten
  als bijmenging, de gewone matrix met haar modificatoren en de vertelling van een handgeschreven
  boorstaat zijn gewone grond; cailloux, tourbe, grès, silex, gypse, schiste, marne en de bank
  blijven vlaggen. Een opmerkingsregel onder een Franse boring telt daardoor drie termen in plaats
  van negentien, en negen van de 145 getelde boringen houden er geen meer over. **Er wordt niets
  vertaald**: een gevlagde term blijft het Franse woord zelf.
  Accenten tellen niet meer mee bij de vergelijking (DOV heeft "vegetale" naast "végétale" en
  "gres" naast "grès"), en de vrouwelijke, de meervouds- en de "-âtre"-vorm zijn uitgangen die er
  vóór de opzoeking afgaan in plaats van losse woorden. De richting van de regel blijft staan: de
  lijst zegt alleen wat GEWOON is, al de rest vlagt.

## [0.3.0] - 2026-09-22

Tweede gebruikersronde. De Locatie-tab zegt wat ze ziet, de lagenboom zet het eigen werk bovenaan,
en drie willekeurige studies per ronde zoeken de fouten die Gent nooit laat zien.

### Toegevoegd
- **Willekeurige studies als zoekmethode** (`scripts/random_study.py`). Het script prikt punten in
  Vlaanderen, bevestigt elk punt tegen `VRBG:Refgem` zodat de plek een gemeentenaam heeft, draait
  er een volledige studie op en leest daarna het eigen resultaat na: blanco bladen (minder dan 2 %
  inkt), kaarten die wel tekenen maar geen enkel feit opleveren, opmerkingsregels met te veel
  termen of met ruiswoorden, en bladen zonder titel. De seed wordt geprint, zodat een reeks te
  herhalen is (`--seed`). Gent is een stad met alles erop en eraan; de fouten die deze ronde boven
  kwamen - een verminkte boornaam, een leeg isopachenblad, een profieltype waarvoor DOV niets
  publiceert - zaten alle drie ergens anders.
- **`compat.house_font`**: de enige plek waar het rapport zijn lettertype kiest (Arial, Liberation
  Sans, DejaVu Sans), voor layouttekst en kaartlabels samen.

### Gewijzigd
- **Eén vlak in de laag is het vlak.** Wie een laag met precies één polygoon aanwijst, hoeft niets
  meer te selecteren. Het tabblad Locatie zegt bovendien vooraf wat het ziet - hoeveel vlakken de
  laag heeft en welk er gekozen is - in plaats van pas na "Start" te weigeren, en een hint die bij
  een andere modus hoort blijft niet staan als je van modus wisselt.
- **De onderzoekszone, de snede en het grondonderzoek van DOV staan bovenaan de lagenboom**, in de
  sessie en in `studie.qgz`; de kaartlagen van de hoofdstukken staan daaronder. Wie de kaart
  openslaat wil zijn eigen zone zien, niet de bovenste WMS-achtergrond.
- **Een isopachenkaart zonder dekking krijgt geen blad meer.** Ligt de locatie buiten de
  isopachenkartering 1/50 000 en staat er geen enkele contour in beeld, dan zegt de kaart niets wat
  de periodetabel van hoofdstuk 4 niet al zegt (daar staat de quartairdikte als getal). De zin over
  de ontbrekende dekking verhuist naar het verzamelblad; staat hoofdstuk 4 uit, dan blijft die zin
  er staan.
- **De krimp-zwelkaart zegt eindelijk iets.** Ze vroeg haar feiten aan
  `plastische_gronden:IndexPlastisch` - een index van de G3Dv3-eenheden die beoordeeld zijn, niet
  van de gevoeligheid. Die index antwoordt alleen waar zo'n eenheid ligt, dus zweeg het rapport in
  Brasschaat (de kaart tekent daar klasse 1) en in Brugge (klasse 4, hoog), en gaf het in Wervik
  een eenheidsnaam in plaats van de klasse. De klasse staat op de kaart zelf
  (`Categorie_gevoeligheid`, GetFeatureInfo in `application/json`) en staat nu in de tabel onder de
  kaart, met de klassewoorden van de dienst erbij (laag [2]). De signalering telt niet langer het
  aantal rijen maar de klasse: vanaf 2 een aandachtspunt, met de klasse in de regel.
- **En ze is leesbaar getekend.** Een blad van zes kleuren zonder iets eronder liet niet zien waar
  iets lag. De kaart krijgt de GRB-basiskaart als ondergrond, staat op 0,6 in plaats van 0,7 en
  gaat van 1:25 000 naar 1:35 000; straten, gebouwen en de waterlopen lezen door en het patroon
  rond de zone staat in beeld. Daaronder staat de sleutel die de dienst zelf tekent
  (GetLegendGraphic: 0 niet-ingedeeld tot 5 zeer hoog), zodat de kleuren een naam hebben.
  `opacity` bereikte het blad tot nu toe alleen via een ondergrond, dus de 0,7 van deze kaart deed
  daar niets - dat staat nu bij het veld.
- **Een grofmazige kaart wordt grofmazig bevraagd.** Het rooster van de krimp-zwelkaart is 100 m,
  en op een meter per beeldpunt antwoordt GeoServer met nul objecten: geen fout, gewoon niets, wat
  in het rapport leest als "de kaart zegt hier niets" boven een kaart die er wel degelijk een
  klasse tekent. Vanaf drie meter per beeldpunt komt het antwoord (live gemeten op drie punten).
  De kaart zegt zelf hoe grof ze bevraagd wil worden (`MapEntry.gfi_m_per_pixel`); de fijne
  kaarten blijven op hun eigen rooster, want grover bevraagd verschuift de GLG van 3,54 naar
  3,52 m.
- **Een profieltype zonder tekeninglink heet ook "niet gepubliceerd".** Gaf de WFS geen link, dan
  werd er niets opgehaald en dus ook niets vastgelegd - terwijl de legendaregel onder de kaart de
  lezer naar het hoofdstuk Bronnen stuurde, waar niets over die tekening stond en de Feiten
  "Bronnen niet beschikbaar: 0" meldden. Hetzelfde feit als een niet-gevonden-pagina, een stap
  eerder bereikt: er valt niets te halen. De eenhedentabel van het kaartblad wordt uit diezelfde
  tekening gesneden, dus een kaartblad waarvan het enige profieltype hier belandt krijgt ook geen
  eenhedenblad; de regel in Bronnen verklaart nu allebei.
- **Geen Python-foutmeldingen meer in het rapport.** "Bron niet beschikbaar: HttpError:
  netwerkfout voor https://.../g3dv3_F: [Errno 11001] getaddrinfo failed" stond zo in het rapport
  van een klant, zowel bij de signaleringen als in de bronnentabel. Er staat nu "de dienst was
  niet bereikbaar", "de dienst antwoordde met foutcode HTTP 502" of "de dienst antwoordde niet
  zoals verwacht"; de technische tekst blijft in het log en in `studie.json`. Toelaten in plaats
  van verbieden: een bericht zonder klassenaam ervoor is door de plugin zelf voor de lezer
  geschreven en gaat ongewijzigd door.
- **Een tekening die DOV niet publiceert heet nu zo.** Het portaal antwoordt voor een onbestaand
  profieltype met HTTP 200 en een DSpace-pagina die "not found" zegt; dat werd gelezen als een
  mislukte ophaling. `dov_portal.says_not_found` herkent die pagina aan haar inhoud, niet aan haar
  status, en zowel de legendaregel als het hoofdstuk Bronnen zeggen dan "DOV publiceert geen
  tekening voor dit profieltype" in plaats van te suggereren dat het aan de verbinding lag.
- **Meer geduld voor een profieltypetekening**: 30 s in plaats van de 15 s van een legenda
  (`layout.DRAWING_TIMEOUT_S`). Het portaal levert een tekening trager dan een kaartdienst een
  legenda, en één keer langer wachten scheelt een gemist blad. Geen eindeloze herkansing.
- **Een bron die een hoofdstuk kort liet, noemt dat hoofdstuk.** De regel in "Niet opgehaalde
  bronnen" zei wat er misging maar niet waar het gat viel; nu staat het hoofdstuk erbij, met het
  advies de bron later opnieuw te raadplegen.
- **De opmerkingsregel bij een boring is korter.** De gewone woordenschat groeide naar 839 woorden
  en wordt nu ook per regel verbreed: kleuren en hun samenstellingen, afgeleiden op -houdend,
  -achtig en -rijk, en oxidatie, verwering en gley gelden als gewoon. Fossiel- en soortnamen
  (`nummulites planulatus`) zijn geen geotechnische zeldzaamheid en worden niet meer gemeld. Franse
  vulwoorden die het corpus bleef tonen (`sable flandrien`, `végétale`, `semblable`) zijn weg. Twee
  stammen aan elkaar zijn samen zo gewoon als apart (`zandleem`), een zandlensje is een lensje, en
  een afgekorte formatienaam (`ieper.`) is net als een soortnaam een datumstempel - `ieperiaan`,
  `aalter` en `asse` stonden al aan de gewone kant. Eén gebruikersregel ging van 28 termen naar 7,
  `1508-B2023-01007-B3` van 11 naar 4, en `kb28d96e-B87` uit een willekeurige run van 12 naar 5 -
  wat overblijft zijn turfballen, silexstukken, veen en twee typfouten van de bron zelf.

### Opgelost
- **De kaartlabels vroegen geen lettertype aan.** `layers._label_format` zette wel een grootte, een
  kleur en een halo, maar geen `QFont`, en dan kiest de renderer er zelf een. Op de overzichtskaart
  van hoofdstuk 5 kwam de boring `kb12d37w-B19` daardoor met vreemde tekens in plaats van `w-` uit
  de export, terwijl dezelfde boring twee bladen verder in de tabel wel klopte. De labels gaan nu
  door `compat.house_font`, net als alle layouttekst.
- **Een infokader liep over zijn eigen tekst.** Het kader kreeg een vaste hoogte; een noot van vier
  regels liep er onderuit. Het meet nu de hoogte die zijn omgebroken tekst nodig heeft.
- **Een GetFeatureInfo-rij zonder waarden telde als antwoord.** Buiten hun dekking geven de
  GxG-diensten een rij terug waarin elk veld leeg is. Die rij werd `rows[0]` en het rapport meldde
  "geen waarde" waar de dienst eenvoudigweg niets weet. Zo'n rij valt nu weg.

## [0.2.0] - 2026-09-18

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
  Twee dingen bepalen wat er van dat alles op papier komt zonder de vlagregel aan te raken.
  Een kort brokstuk met een punt is een afkorting en wordt niet gedrukt: "Num. planulatus" zette
  eerst het zinloze "num" in het rapport. En soortnamen van fossielen (`FOSSILS`) worden
  onderdrukt, net als de gewone woorden: ze zeggen in welke formatie je staat, niet dat je iets
  zult raken. Een boring die alleen soortnamen noemt krijgt dus geen opmerkingsregel en geen
  signalering meer. De geciteerde zin verandert niet - staat er "Num. planulatus" in, dan blijft
  dat staan. Een schelpenbank blijft wel vlaggen: die draagt haar eigen woord.
- **De diktekaart van het Quartair toont nu de isopachen die DOV zelf tekent.** Ze wees naar
  `dov-pub:Quartair_Isopachen`, een grove reeks van 780 lijnen voor heel Vlaanderen waarvan de
  dichtstbijzijnde 5,6 km van de Gentse zone lag - vandaar een leeg kaartbeeld, een schaal van
  1:100 000 en een tabel met afstanden. De kaart is nu `quartair:qisopachen_quartair_50k`, de
  kartering op 1:50 000: rond diezelfde zone liggen er vier contouren binnen 300 m (5, 10 en twee
  van 2,5 m). Ze staat op 1:25 000, de dienst tekent de dikte op de lijnen zelf, en de tabel met
  afstanden is vervangen door één regel: welke diktes er in beeld liggen, en daarnaast de
  modelwaarde die G3Dv3 op het representatieve punt berekent. Die twee mogen verschillen - op de
  Gentse zone zegt het model 3,78 m waar de kaart 5 tot 10 m contouren toont - en dat verschil
  blijft staan zoals het is: het is informatie voor wie het rapport leest, geen fout om glad te
  strijken.

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
- **De isopachen dragen leesbare diktecijfers.** De dienst tekent ze wel, maar dun, klein en grijs:
  boven de GRB-ondergrond vielen ze weg. De kaart vraagt haar eigen belettering aan met een SLD in
  de GetMap - dezelfde lijnen van de dienst, maar vette zwarte cijfers met een witte halo, langs de
  lijn in plaats van erdoorheen, en om de zoveel centimeter herhaald. Diezelfde witte halo staat nu
  ook om de sondeer- en boornummers op de overzichtskaart, waar ze in het midden tot een
  onleesbare veeg samenliepen; wat daar nog botst wordt weggelaten in plaats van overheen getekend.
- **Alle "geen gegevens"-antwoorden staan gebundeld op het laatste blad.** Een kaart zonder
  eenheden in de zone droeg een leeg legendablok onder haar kaartbeeld, en een stapel van die
  blokken midden in hoofdstuk 3 zei vijf keer dezelfde zin. Elke kaart houdt haar eigen kaartblad;
  het lege blok eronder verdwijnt en de zin komt op een gebundelde pagina achteraan, gegroepeerd
  per antwoord ("Geen kaarteenheden binnen de zone. Geldt voor: A, B"). Er gaat niets verloren:
  het hoofdstuk Bronnen noemt nog altijd elke kaart met haar eigen status.
- **Een figuur die krimpt om mee te passen, past ook echt.** De kolom van HCOV v2 kreeg een blad
  voor zichzelf terwijl de tabel erboven een kwart blad vulde - de figuur werd tot op de
  millimeter van de beschikbare ruimte gekrompen, waarna de controle "past dit?" dezelfde som
  twee keer berekende en op 1e-14 mm omviel. Hoofdstuk 4 toont nu alle vier de modellen op
  dezelfde manier: tabel en kolom samen op een blad.
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
  toont nog altijd elke sondering binnen de straal, op afstand gesorteerd, met de regel als noot
  erboven: waarom een elektrische van 300 m getekend is en een mechanische van 40 m niet. Zo'n
  noot krijgt nu de hoogte van zijn eigen regels in plaats van een vaste strook van twee.
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

[Unreleased]: https://github.com/Vorsie/dov-desktopstudie/compare/v0.4.1...HEAD
[0.4.1]: https://github.com/Vorsie/dov-desktopstudie/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/Vorsie/dov-desktopstudie/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/Vorsie/dov-desktopstudie/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/Vorsie/dov-desktopstudie/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/Vorsie/dov-desktopstudie/releases/tag/v0.1.0
