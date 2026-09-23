"""Geen bestand dat een buitenstaander leest, mag beweren dat een oude versie de huidige is.

De regel in Robins woorden: als op de GitHub-pagina nog een oude versie staat, klopt het niet. Dat
is twee keer gebeurd - README en SECURITY.md bleven "v0.3.0" zeggen terwijl v0.4.2 uit was - omdat
het nummer in de lopende tekst stond en een release-commit alleen `metadata.txt`, `pyproject.toml`
en de changelog aanraakt.

Een versienummer op zich is niet het probleem: "115 bladen in v0.1.0 en 62 in 0.2.0" is geschiedenis
en hoort te blijven staan, en "QGIS 3.40.15" gaat over iets anders. Wat verouderd raakt, is een zin
die een nummer aan het HEDEN vastknoopt. Daar zoekt deze test op, plus op de twee plaatsen waar het
nummer per se moet kloppen.
"""
from __future__ import annotations

import re
from pathlib import Path

from tests.versions import ROOT, pyproject_version

# Wat een lezer op GitHub onder ogen krijgt. `CHANGELOG.md` hoort er niet bij: die noemt per
# definitie elke oude versie, en "## [0.3.0] - 2026-09-22" is juist wat hij moet doen.
PUBLIEK = ("README.md", "SECURITY.md", "CONTRIBUTING.md", ".github/ISSUE_TEMPLATE/bug_report.yml")
# Woorden die van een nummer een bewering over nu maken.
NU = ("status:", "op dit ogenblik", "momenteel", "op dit moment", "huidige versie", "laatste release")
# De plugin draagt drie getallen; QGIS-versies (3.34, 3.40.15) worden hieronder uitgezonderd.
VERSIE = re.compile(r"\bv?(\d+\.\d+\.\d+)\b")


def _regels_die_nu_beweren(pad: Path):
    """Regels die een versienummer aan het heden knopen, met hun regelnummer."""
    for nummer, regel in enumerate(pad.read_text(encoding="utf-8").splitlines(), start=1):
        lager = regel.lower()
        if any(woord in lager for woord in NU) and VERSIE.search(regel):
            yield nummer, regel.strip()


def test_geen_enkel_publiek_bestand_knoopt_een_versienummer_aan_het_heden():
    """Zeg "de laatste release" en laat de badge of de releasepagina het nummer geven."""
    gevonden = {naam: list(_regels_die_nu_beweren(ROOT / naam)) for naam in PUBLIEK}
    fout = {naam: regels for naam, regels in gevonden.items() if regels}
    assert not fout, (
        f"deze regels beweren welke versie de huidige is en verouderen dus bij elke release: {fout}. "
        "Schrijf 'de laatste release' zonder nummer, of laat de badge het zeggen."
    )


def test_het_voorbeeld_in_het_bugformulier_toont_de_huidige_versie():
    """Een invulhint met een oude versie leest als verwaarlozing, en hij staat er maar één keer."""
    tekst = (ROOT / ".github" / "ISSUE_TEMPLATE" / "bug_report.yml").read_text(encoding="utf-8")
    blok = tekst.split("id: plugin", 1)
    assert len(blok) == 2, "het bugformulier heeft geen veld met id 'plugin' meer"
    hint = re.search(r'placeholder:\s*"([^"]+)"', blok[1])
    assert hint, "het versieveld van het bugformulier heeft geen placeholder"
    assert hint.group(1) == pyproject_version()


def test_de_plugin_en_het_project_dragen_hetzelfde_nummer():
    """Wat `metadata.txt` zegt is wat QGIS toont; wat `pyproject.toml` zegt bepaalt de zipnaam."""
    metadata = (ROOT / "desktopstudie" / "metadata.txt").read_text(encoding="utf-8")
    match = re.search(r"^version=(.+)$", metadata, re.MULTILINE)
    assert match, "metadata.txt declareert geen versie"
    assert match.group(1).strip() == pyproject_version()
