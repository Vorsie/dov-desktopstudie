# Wat verandert er, en waarom

<!-- Twee, drie zinnen. Wat deed de plugin vóór deze wijziging, wat doet ze erna, en welk
probleem lost dat op. Hoort er een issue bij, verwijs ernaar: "Sluit #12". -->

## Getest

Kruis aan wat je gedraaid hebt, en plak de samenvattingsregel van pytest erbij als je ze hebt.

- [ ] `tests/core` (gewone venv)
- [ ] `tests/scripts` (gewone venv)
- [ ] `tests/qgis` (Python van QGIS, of `qgis/qgis:release-3_34` / `qgis/qgis:latest`)
- [ ] live-tests (`-m live`, raken de echte diensten van DOV en geopunt)
- [ ] `ruff check .`

## Naar het resultaat gekeken

- [ ] Een echte studie gedraaid en de bladen bekeken (`run_headless.py --paginas`, of de plugin in
      QGIS). Plaats: <!-- adres of X/Y -->
- [ ] Niet nodig, want deze wijziging raakt het rapport niet.

<!-- Groene tests bewijzen niet dat er iets leesbaars uit de printer komt. Raakte je de layout,
een figuur of een kaart, plak dan gerust een schermafdruk van het blad. -->

## Voor je op "Ready for review" klikt

- [ ] Eén bestand per commit, Conventional Commits, onderwerp in het Engels en hoogstens 72 tekens.
- [ ] De test staat vóór de implementatie die haar groen maakt.
- [ ] Nieuwe laagnamen, stijlnamen, veldnamen of URL's zijn live tegen de dienst geverifieerd.
- [ ] `CLAUDE.md`, `README.md` of `CHANGELOG.md` bijgewerkt waar deze wijziging ze achterhaald
      maakt.
