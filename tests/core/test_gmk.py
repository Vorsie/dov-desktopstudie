"""De grondmechanische kaart: het kaartblad volgt uit de zone, de gebruiker kiest alleen thema's.

Robin: "de opdeling van de kaartbladen moet de user zich niet mee bezighouden he, dat is op basis
van bevraagde zone in qgis". Dus geen keuzelijst met drieentwintig bladnummers - de zonelaag
`gmk:gekarteerde_zones_grondmechanischekaart` zegt welk blad onder de zone ligt, en de aangevinkte
thema's bepalen welke platen van DAT blad in het rapport komen.

Op thema en niet op plaatnummer, want dat nummer betekent per blad iets anders: Plaat X is op
14.5.8 Gent-Evergem de Basis van het Kwartair, op 14.6.5 Gent-Desteldonk is dat Plaat VIII, en op
22.1.4 Gent-Centrum heet ze "Basis van de kwartaire sekwentie" en bestaat ze alleen als vectorlaag.
Alle namen geharvest uit GetCapabilities van de `gmk`-workspace op 2026-10-04.
"""
from __future__ import annotations

import pytest

from desktopstudie.core import catalogue as c

# Vier thema's bestaan op alle drieentwintig bladen; de Kwartairbasis op twintig.
UNIVERSEEL = ("documentatie", "aanvulling", "zonering", "hydrogeologie")


def test_elk_kaartblad_kent_de_vier_thema_s_die_overal_bestaan():
    assert len(c.GMK_SHEETS) == 23
    for nummer, (naam, platen) in c.GMK_SHEETS.items():
        assert naam, nummer
        for thema in UNIVERSEEL:
            assert thema in platen, f"{nummer} mist {thema}"
            assert platen[thema].startswith("kb_"), platen[thema]


def test_de_kwartairbasis_bestaat_niet_op_elk_blad():
    """22.1.2 Gent-Wondelgem heeft maar acht platen en geen Kwartairbasis. Dat is een feit over de
    kaart: er hoort geen leeg blad voor te komen en geen melding dat iets mislukte."""
    met = [nr for nr, (_naam, platen) in c.GMK_SHEETS.items() if "kwartairbasis" in platen]

    assert len(met) == 20
    assert "kwartairbasis" not in c.GMK_SHEETS["22.1.2"][1]


def test_de_platen_van_een_blad_worden_als_gewone_kaarten_gebouwd():
    """Een MapEntry kan geen laagnaam dragen die pas na de zonevraag bekend is, dus worden ze
    gebouwd. Het blijven gewone entries, zodat de pijplijn en de layout er niets van merken."""
    entries = c.gmk_entries("22.1.6", ("documentatie", "zonering"))

    assert [e.id for e in entries] == ["gmk_documentatie", "gmk_zonering"]
    for entry in entries:
        assert entry.chapter == "geologie"
        assert entry.wms_url == c.GMK_WMS_URL
        assert entry.wms_layer.startswith("kb_22_1_6_")
        assert "22.1.6" in entry.title and "Gent-Sint-Pieters" in entry.title
        assert entry.fact_mode is None, "een scan van een plaat heeft geen feitentabel"


def test_een_thema_dat_dit_blad_niet_heeft_levert_geen_kaart():
    entries = c.gmk_entries("22.1.2", ("zonering", "kwartairbasis"))

    assert [e.id for e in entries] == ["gmk_zonering"]


def test_de_thema_s_komen_in_de_volgorde_van_de_keuzelijst_en_niet_van_de_gebruiker():
    """Twee runs van dezelfde studie horen dezelfde bladvolgorde te geven."""
    omgekeerd = c.gmk_entries("15.3.6", ("zonering", "documentatie"))
    vooruit = c.gmk_entries("15.3.6", ("documentatie", "zonering"))

    assert [e.id for e in omgekeerd] == [e.id for e in vooruit]


def test_buiten_de_gekarteerde_zones_is_er_geen_grondmechanische_kaart():
    """De kaart bestaat alleen voor Gent en Antwerpen. Een onbekend bladnummer levert niets."""
    assert c.gmk_entries("", ("documentatie",)) == []
    assert c.gmk_entries("99.9.9", ("documentatie",)) == []


def test_de_keuzelijst_noemt_de_thema_s_in_het_nederlands():
    """De vinkjes staan in de dialoog, dus de labels zijn leestekst en geen sleutels."""
    sleutels = [sleutel for sleutel, _label in c.GMK_THEMES]

    assert sleutels == list(UNIVERSEEL) + ["kwartairbasis"]
    for _sleutel, label in c.GMK_THEMES:
        assert label[0].isupper(), label
    assert set(c.GMK_DEFAULT_THEMES) <= set(sleutels)


def test_de_zonelaag_wordt_bij_naam_genoemd_op_een_plek():
    """Het blad opzoeken is een WFS-vraag op die laag; de velden heten `kb_nummer` en `kb_naam`
    (live 2026-10-04: Gent-centrum -> 22.1.6, Antwerpen -> 15.3.6, Brugge -> nul zones)."""
    assert c.GMK_ZONES_TYPENAME == "gmk:gekarteerde_zones_grondmechanischekaart"
    assert c.GMK_SHEET_FIELD == "kb_nummer"


@pytest.mark.parametrize("nummer", ["22.1.6", "15.3.6", "14.5.8"])
def test_elke_laagnaam_hoort_bij_het_blad_waar_hij_onder_staat(nummer):
    """Een plaat van het verkeerde blad tekent de buurgemeente, en niets faalt."""
    plat = nummer.replace(".", "_")
    for _thema, laag in c.GMK_SHEETS[nummer][1].items():
        assert laag.startswith(f"kb_{plat}_"), f"{nummer}: {laag}"


def test_de_gebouwde_platen_komen_mee_als_kaarten_van_de_studie():
    """De platen staan niet in de catalogus, dus elke plek die de catalogus doorloopt - de
    rapportbladen, de bronnenlijst, de lagen, de kaartbeelden - moet ze er bij krijgen. Anders
    staat de plaat in het project maar niet in het rapport, of omgekeerd."""
    gebouwd = c.gmk_entries("22.1.6", c.GMK_DEFAULT_THEMES)

    alles = c.entries(extra=gebouwd)
    geologie = c.entries("geologie", extra=gebouwd)
    historisch = c.entries("historisch", extra=gebouwd)

    assert [e.id for e in gebouwd] == [e.id for e in alles if e.id.startswith("gmk_")]
    assert [e.id for e in gebouwd] == [e.id for e in geologie if e.id.startswith("gmk_")]
    assert not [e for e in historisch if e.id.startswith("gmk_")], "een plaat hoort bij de geologie"


def test_een_keuze_van_kaarten_laat_de_gebouwde_platen_staan():
    """`only` is de vinklijst van de gebruiker, en daar staan de platen niet in: ze bestaan pas
    als de zone bekend is. Een lege keuze mag ze dus niet wegfilteren."""
    gebouwd = c.gmk_entries("15.3.6", ("zonering",))

    gekozen = c.entries(only=["bodemkaart"], extra=gebouwd)

    assert [e.id for e in gekozen] == ["bodemkaart", "gmk_zonering"]
