# Fixtures

Echte profieltypetekeningen van het DOV-documentportaal, opgehaald door een studie en daarna
ingekort tot de bovenste 260 pixelrijen: de kop, de horizontale lijn eronder en het begin van de
eenhedentabel. De pixels zelf zijn onaangeroerd (geen herschaling, geen palet), dus de rijnummers
in `desktopstudie/qgis/images.py` blijven op deze bestanden na te meten. De rest van de tekening
is weggelaten omdat een testmap geen beeldarchief is.

Twee kaartbladen, want de dienst tekent ze niet gelijk:

- **22010** (980 x 703, hier 980 x 260) - kop met kleurvlak, lettercode en één regel omschrijving,
  dan de titel "Eenheden op kaartblad 22", dan de lijn op rij 145.
- **07020** en **07029** (1648 x 1200, hier 1648 x 260) - kop met een klein genummerd kleurvlak en
  een omschrijving van vier regels, dan een rij textuurvlakjes, dan de lijn op rij 189. Geen enkele
  gekleurde pixel in de eerste 240 rijen, dus een zoeker die op een kleurvlak afgaat vindt hier
  niets.

| Bestand | Bron-URL | Datum |
|---|---|---|
| `quartair_22010.png` | <https://datasets.omgeving.vlaanderen.be/be.vlaanderen.omgeving.distribution.geo.e58c3358-e149-42b6-9229-c3a9ac88c3d4.DOV_Quartair_50000_22010_png> | 2026-09-17 |
| `quartair_07020.png` | <https://datasets.omgeving.vlaanderen.be/be.vlaanderen.omgeving.distribution.geo.e58c3358-e149-42b6-9229-c3a9ac88c3d4.DOV_Quartair_50000_07020_png> | 2026-09-22 |
| `quartair_07029.png` | <https://datasets.omgeving.vlaanderen.be/be.vlaanderen.omgeving.distribution.geo.e58c3358-e149-42b6-9229-c3a9ac88c3d4.DOV_Quartair_50000_07029_png> | 2026-09-22 |
