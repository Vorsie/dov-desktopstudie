"""Een kaart die niet over deze zone gaat, hoort geen blad te krijgen.

Robin, nadat hij vier zulke bladen in het Gentse proefrapport zag: "natuurlijk moeten die niet
opgenomen worden als er geen data is". Het ging om de drie geulenkaarten en de watertoets vanuit de
zee, kaarten die maar over een deel van Vlaanderen gaan; buiten dat deel stond er een blad met
alleen de mededeling dat de kaart daar niet bestaat.

Twee soorten leegte mogen daar niet in meegaan.

Leegte die het ANTWOORD is. De watertoets pluviaal is voor heel Vlaanderen gemodelleerd, dus geen
rij betekent "niet overstromingsgevoelig" - dat is informatie waar een lezer naar zocht, en het
blad blijft. Daarom beslist de catalogus per kaart (`skip_when_empty`) en niet een regel die elke
lege tabel wegneemt.

Leegte die een MISLUKKING is. Een bron die niet antwoordde heeft geen rijen, net als een bron die
niets vond, en een blad weglaten zou de fout verbergen. `model.facts_of` houdt die twee al apart:
`None` is niet gevraagd of mislukt, `[]` is gevraagd en niets gevonden. Alleen de tweede verdwijnt.
"""
from __future__ import annotations

from desktopstudie.core import catalogue, model
from desktopstudie.core import report_content as rc
from desktopstudie.core.model import MapFact, StudyResult, StudyZone

REGIONAAL = "geulen_luchtfotos"
OVERAL = "watertoets_pluviaal"


def _result(gent_ring, facts=()):
    r = StudyResult(zone=StudyZone(ring=gent_ring, name="Gent test"), created_at="2026-10-05T08:00:00")
    r.map_ids = catalogue.default_map_ids()
    for map_id, rows in facts:
        r.map_facts.append(MapFact(map_id, catalogue.by_id(map_id).title, list(rows)))
    return r


def test_de_catalogus_zegt_van_welke_kaarten_een_leeg_antwoord_het_blad_kost():
    """Alleen kaarten die over een DEEL van Vlaanderen gaan. Een kaart waarvan leegte het antwoord
    is, mag hier niet tussen staan."""
    mag_weg = {e.id for e in catalogue.entries() if e.skip_when_empty}

    assert mag_weg == {"geulen_luchtfotos", "geulen_sinds_1570", "geulen_voor_1570", "watertoets_zee"}
    for map_id in ("watertoets_pluviaal", "watertoets_fluviaal", "erosie", "ovam", "krimp_zwel",
                   "grondverschuiving_gevoeligheid", "pfas_no_regret"):
        assert not catalogue.by_id(map_id).skip_when_empty, map_id


def test_een_regionale_kaart_zonder_data_krijgt_geen_blad(gent_ring):
    result = _result(gent_ring, [(REGIONAAL, [])])

    blijft = model.printed_maps(result, catalogue.entries(only=result.map_ids))

    assert REGIONAAL not in [e.id for e in blijft]


def test_dezelfde_kaart_met_data_houdt_haar_blad(gent_ring):
    result = _result(gent_ring, [(REGIONAAL, [{"soort": "geulen_naar_orthofoto"}])])

    blijft = model.printed_maps(result, catalogue.entries(only=result.map_ids))

    assert REGIONAAL in [e.id for e in blijft]


def test_een_bron_die_niet_antwoordde_houdt_haar_blad(gent_ring):
    """Geen MapFact betekent mislukt of niet gevraagd. Het blad meldt dan "Bron niet beschikbaar",
    en dat is precies wat een lezer moet zien - een weggelaten blad zou de fout verbergen."""
    result = _result(gent_ring)

    blijft = model.printed_maps(result, catalogue.entries(only=result.map_ids))

    assert REGIONAAL in [e.id for e in blijft]
    assert model.facts_of(result, REGIONAAL) is None


def test_een_kaart_waarvan_leegte_het_antwoord_is_houdt_haar_blad(gent_ring):
    """"Niet overstromingsgevoelig" is informatie waar de lezer naar zocht."""
    result = _result(gent_ring, [(OVERAL, [])])

    blijft = model.printed_maps(result, catalogue.entries(only=result.map_ids))

    assert OVERAL in [e.id for e in blijft]


def test_het_rapport_laat_het_blad_weg_maar_het_bronnenhoofdstuk_noemt_de_kaart(gent_ring):
    """Weglaten mag geen verdwijnen worden: de lezer hoort te kunnen zien dat de kaart bevraagd is
    en wat eruit kwam, anders lijkt ze overgeslagen."""
    result = _result(gent_ring, [(REGIONAAL, []), (OVERAL, [])])

    report = rc.build_report(result, rc.ReportMeta(project="P", author="A", company="C"))
    geologie = next(ch for ch in report.chapters if ch.title == "Geologie en bodem")
    bladen = [p.map_id for p in geologie.pages if isinstance(p, rc.MapPage)]

    assert REGIONAAL not in bladen
    assert OVERAL in bladen
    titel = catalogue.by_id(REGIONAAL).title
    bronnen = next(ch for ch in report.chapters if ch.title == "Bronnen en licenties")
    gedrukt = "\n".join(str(getattr(page, "rows", "")) + str(getattr(page, "html", ""))
                        for page in bronnen.pages)
    assert titel in gedrukt, "de kaart hoort in de bronnenlijst te blijven staan"
