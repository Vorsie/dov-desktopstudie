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
