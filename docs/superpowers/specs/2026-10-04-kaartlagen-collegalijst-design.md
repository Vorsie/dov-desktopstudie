# Kaartlagen uit de collegalijst - ontwerp

Op 2026-09-23 stuurde een collega van MOW een lijst door uit de cursus grondonderzoek: kaartlagen
die de lesgever standaard bekijkt bij een deskstudie en die de plugin nog niet had. Robin keurde op
2026-10-04 de uitvoering goed ("geulen bij geologie houden, implementeer het zo").

Elke dienst is op 2026-10-04 live bevraagd. De laagnamen hieronder komen uit GetCapabilities en de
veldnamen uit DescribeFeatureType, niet uit de doorgestuurde tabel - die klopte op vier punten niet
(zie "Wat er in de mail fout stond").

## Wat erbij komt

28 nieuwe `MapEntry`'s; de catalogus gaat van 29 naar 57 entries.

| Kaart | hoofdstuk | WMS-dienst | laag | feiten |
|---|---|---|---|---|
| Winterorthofoto 2012 t/m 2025 (14 stuks) | historisch | `https://geo.api.vlaanderen.be/OMW/wms` | `OMWRGB12VL` … `OMWRGB25VL` | geen |
| Winterorthofoto 2013-2015, 10 cm | historisch | `https://geo.api.vlaanderen.be/OGW/wms` | `OGWRGB13_15VL` | geen |
| Zomerorthofoto 2009, 2012, 2015, 2018, 2021, 2024 | historisch | `https://geo.api.vlaanderen.be/OMZ/wms` | `OMZRGB09VL` … `OMZRGB24VL` | geen |
| Archeologienota's | historisch | `https://geo.onroerenderfgoed.be/geoserver/wms` | `vioe_geoportaal:archeologienotas` | WFS op eigen dienst |
| Geulenstelsel naar luchtfoto's | geologie | DOV-workspace `dijken` | `geulenstelsel_naar_luchtfotos` | WFS, veld `soort` |
| Geulenstelsel sinds 1570 | geologie | DOV-workspace `dijken` | `geulenstelsel_sinds_1570` | WFS, veld `periode` |
| Geulenstelsel voor 1570 | geologie | DOV-workspace `dijken` | `geulenstelsel_voor_1570` | WFS, veld `periode` |
| Waterlopen (VHA) | ligging | `https://geo.api.vlaanderen.be/hy/wms` | `HY.Network` | WFS op een ANDERE dienst |
| Peilmeetstations waterstand | geologie | `https://inspirepub.waterinfo.be/arcgis/services/meetpunten/MapServer/WMSServer` | `3` | GetFeatureInfo |
| Watertoets vanuit de zee | geologie | `WATERINFO_WMS_URL` met `kind="vanuit_de_zee"` | `0` | GetFeatureInfo |

### Geverifieerde feitenvelden

- `vioe_geoportaal:archeologienotas` (WFS `https://geo.onroerenderfgoed.be/geoserver/wfs`):
  `naam`, `type_naam`, `datum_ind`, `opgraving`, `bh_in_situ`, `uri`. Live bij Gent: 193 nota's
  binnen 1500 m, `application/json`, `urn:ogc:def:crs:EPSG::31370`. De `vioe_intern:`-varianten
  zijn niet publiek en blijven buiten de catalogus.
- `VHAWaterlopen:Wlas` (WFS `https://geo.api.vlaanderen.be/VHAWaterlopen/wfs`): `NAAM`,
  `LBLCATC` (categorie), `BEHEER`, `BEKNAAM` (bekken). Live bij Gent: de Ketelvest, "Bevaarbaar",
  "Bekken van de Gentse Kanalen". Het geometrieveld heet hier `SHAPE`; `dov_wfs.geometry_field`
  zoekt dat al per laag op met DescribeFeatureType, dus daar is niets aan te doen.
- De drie `dijken:geulenstelsel_*` typenames worden ook door de GLOBALE DOV-WFS bediend (een leeg
  antwoord, geen fout), dus die houden `wfs_url` op de standaard.

### Wat de geulenkaarten werkelijk zijn

Niet de kreekruggen van de kustpolders. De drie lagen bevatten 450, 55 en 6 features en liggen
rond X 137-140 km, Y 217-222 km - de Schelde bij Bornem/Temse. Workspace `dijken`: het zijn
dijkdoorbraakgeulen. Voor elke studie buiten die strook antwoorden ze leeg. Ze komen er zoals
gevraagd in; of ze een blad verdienen waar niets ligt is een open punt (zie onderaan).

## De ene structurele wijziging

`study.py` stuurt elke WFS-feitenvraag naar `catalogue.DOV_WFS_URL`:

```python
url = entry.wms_url if entry.fact_mode == "gfi" else catalogue.DOV_WFS_URL
```

Twee van de nieuwe bronnen hebben hun eigen WFS. Daarom krijgt `MapEntry` een veld
`wfs_url: str = DOV_WFS_URL` en wordt die regel `entry.wfs_url`. De 29 bestaande entries
veranderen niet: de standaard is wat ze nu al krijgen.

Geen tweede wijziging nodig. Het geometrieveld verschilt per dienst (`geom` tegen `SHAPE`), maar
`dov_wfs` zoekt dat al op en onthoudt het per typename.

## De instelling voor de luchtfoto's

Eenentwintig orthofoto-jaren horen niet allemaal op papier: het rapport staat op 62 bladen en ging
in v0.2.0 juist van 115 naar 62. `study.Settings.map_ids` bestaat al (`None` = alle ingeschakelde
entries), dus er is geen nieuw filtermechanisme nodig.

- `qgis/settings.py` bewaart de gekozen orthofoto-ids. Standaard: `ortho_ogw_2013_15`,
  `ortho_omw_2018`, `ortho_omw_2025`, `ortho_omz_2009`, `ortho_omz_2015`, `ortho_omz_2021`.
- `qgis/dialog.py` toont ze als één aanvinklijst (`QListWidget` met checkboxes in een scrollbaar
  vak; eenentwintig losse checkboxen is geen tab meer).
- De dialoog stelt `map_ids` samen: alle niet-orthofoto-ids plus de aangevinkte jaren.

**Gevolg, bewust aanvaard:** een niet-aangevinkt jaar wordt ook geen laag in `studie.qgz` en wordt
niet opgehaald. Dat houdt de run snel - geen eenentwintig extra GetMap's - en je ziet een jaar door
het aan te vinken en opnieuw te draaien, wat op een warme cache snel is. Het alternatief (alle
jaren altijd als laag, maar zes op papier) kost eenentwintig GetCapabilities per run.

## Rapportgroei

62 naar ongeveer 75 bladen met de standaardselectie: zes orthofoto's, archeologienota's, drie
geulenkaarten, waterlopen, peilmeetstations, watertoets vanuit de zee, plus de leeswijzers
daarachter. Dat is de prijs van de volledige lijst, en met de instelling is de orthofoto-helft
ervan terug te draaien zonder code te wijzigen.

## Wat er in de mail fout stond

Niet overnemen:

1. `oi/wms?layers=OI.OrthoimageCoverage.OMWRGB16VL` en `…OMWRGB18VL` bestaan niet. `oi/wms` heeft
   vier lagen (`OI.OrthoimageCoverage.OMW`, `.OMZ.RGB`, `.OMZ.PAN`, `.OMZ.CIR`); de jaarlagen
   staan op `OMW/wms` en `OMZ/wms`.
2. `OI.OrthoimageCoverage.OMW` is "meest recente winter", niet 2025. 2025 is `OMWRGB25VL`.
3. Vijf OMZ-rijen met dezelfde URL: de laagnaam onderscheidt het jaar, niet de URL.
4. `https://geo.api.vlaanderen.be/VHAWaterlopen/wms` geeft nul lagen op 1.1.1 en op 1.3.0. Het
   kaartbeeld komt van `hy/wms` met `HY.Network`; de WFS van VHAWaterlopen werkt wel.

## Tests, in deze volgorde

Elke regel eerst rood, in de woorden van de regel:

1. `wfs_url` valt terug op de DOV-WFS, en `study` vraagt de feiten op het adres van de entry -
   niet op een vast adres.
2. De catalogus bevat elk van de 28 nieuwe entries met de geverifieerde laagnaam en dienst.
3. De dialoog bewaart de orthofoto-keuze en leest hem terug.
4. `map_ids` bevat precies de aangevinkte orthofoto's plus alle niet-orthofoto-entries.
5. Achter `-m live`: van elke nieuwe dienst één GetMap, en van elke feitenbron één vraag met
   antwoord. Dit is wat de bestaande live-suite al doet voor de 29 bestaande kaarten.

## Open punt

De drie geulenkaarten krijgen een blad ook waar de dataset niet ligt, en dat is in Vlaanderen
bijna overal. Een veld `skip_when_empty` zou zo'n blad weglaten en de bron in het bronnenhoofdstuk
noemen. Buiten deze scope gehouden tot Robin het vraagt.

## Grondmechanische kaarten (bijgevraagd op 2026-10-04)

Robin vroeg deze er tijdens het ontwerp bij, "optioneel, met aanvinken", en voegde daarna toe: "de
opdeling van de kaartbladen moet de user zich niet mee bezighouden, dat is op basis van bevraagde
zone in qgis". Dus geen keuzelijst voor het kaartblad - de zone bepaalt het.

### Wat de dienst aanbiedt

Workspace `gmk` op de DOV-GeoServer, `https://www.dov.vlaanderen.be/geoserver/gmk/wms`:
23 kaartbladen met elk 8 tot 11 platen, als scan van de originele plaat (`kb_<blad>_p<n>_r`) en
deels als vector (`_v`). 250 rasterlagen, 396 vectorlagen. Alleen Gent en Antwerpen; de rest van
Vlaanderen is niet gekarteerd.

`gmk:gekarteerde_zones_grondmechanischekaart` geeft het kaartblad bij een coordinaat, met de
velden `kb_nummer` en `kb_naam`. Live 2026-10-04: Gent-centrum -> `22.1.6 Gent-Sint-Pieters`,
Antwerpen -> `15.3.6 Antwerpen-Centrum`, Brugge -> nul zones.

### Waarom het op thema moet en niet op plaatnummer

De plaatnummering verschilt per blad. Plaat X is op 14.5.8 Gent-Evergem de Basis van het Kwartair,
op 14.6.5 Gent-Desteldonk is dat Plaat VIII, en op 22.1.4 Gent-Centrum heet ze "Basis van de
kwartaire sekwentie" en bestaat ze alleen als vectorlaag. Een vinkje "Plaat X" zou dus per blad
iets anders aanvinken.

Vier thema's bestaan op alle 23 bladen, geharvest uit de capabilities:

| Thema | dekking |
|---|---|
| Dokumentatie (de boringen en sonderingen waarop het blad rust) | 23/23 |
| Dikte van de aangevulde en vergraven gronden | 23/23 |
| Zonering | 23/23 |
| Hydrogeologische gegevens | 23/23 |
| Basis van het Kwartair | 20/23 |

`22.1.2 Gent-Wondelgem` heeft maar acht platen en geen Kwartairbasis; `22.1.4` en `22.1.6` hebben
die alleen als vector. Regel: de scan waar die bestaat, de vectorlaag als terugval, en waar het
thema niet bestaat komt er geen blad maar een regel in het bronnenhoofdstuk.

### Ontwerp

- `catalogue.GMK_SHEETS`: geharvestte tabel `kb_nummer -> (kb_naam, {thema: laagnaam})`, 23 rijen.
  Eenmalig geoogst uit GetCapabilities, zoals de woordenlijst van `lithology`; een script hoeft er
  niet voor te blijven staan, de herkomst staat in de docstring.
- `catalogue.gmk_entries(kb_nummer, themes)` bouwt de `MapEntry`'s voor dat blad. Een `MapEntry`
  kan geen laagnaam dragen die pas na de zonevraag bekend is, dus worden ze gebouwd in plaats van
  letterlijk in de catalogus te staan. Het blijven gewone `MapEntry`'s, dus de rest van de
  pijplijn en de layout merken er niets van.
- `study` zoekt het blad op met een WFS-vraag `INTERSECTS(geom, zone)` op de zonelaag en neemt het
  blad van het representatieve punt (`REPRESENTATIVE_POINT`, de bestaande conventie). Raakt de
  zone ook een ander blad, dan wordt dat genoemd maar niet getekend.
- Buiten Gent en Antwerpen: geen bladen, en een regel in het bronnenhoofdstuk dat de
  grondmechanische kaart daar niet bestaat. Dat is een feit over de bron, geen mislukking.
- `settings.py` bewaart de aangevinkte thema's; standaard Dokumentatie, Aanvulling en Zonering.

### Rapportgroei, bijgewerkt

Met de standaardselectie: 62 -> ongeveer 78 bladen (zes orthofoto's, archeologienota's, drie
geulenkaarten, waterlopen, peilmeetstations, watertoets vanuit de zee, drie grondmechanische
platen, plus leeswijzers). Binnen Gent en Antwerpen; daarbuiten drie bladen minder.
