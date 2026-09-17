"""De woordenschat van een boorbeschrijving: wat gewoon is, en wat daarom opvalt.

De lijsten zijn gecureerd op 3630 lagen uit 512 boringen rond twaalf punten verspreid over
Vlaanderen (`scripts/lithology_vocabulary.py`); deze tests pinnen de regels, niet de lijst zelf.
"""
from __future__ import annotations

from desktopstudie.core import lithology
from desktopstudie.core.model import LithologyLayer


def _layer(top, base, text, kind="beschrijving"):
    return LithologyLayer(top_m=top, base_m=base, description=text, kind=kind)


def test_a_plain_description_says_nothing_worth_flagging():
    """"Matig fijn zand, weinig kleihoudend, grijsgroen, vochtig" is de gewone grond van
    Vlaanderen. Zou zo'n regel vlaggen, dan is de melding waardeloos."""
    layers = [_layer(0.0, 2.0, "Matig fijn zand, weinig kleihoudend, grijsgroen, vochtig"),
              _layer(2.0, 4.0, "grijze zandige klei met dunne zandige kleilagen, stevig")]

    assert lithology.notable_terms(layers) == []


def test_a_word_nobody_listed_surfaces_by_itself():
    """De lijst bepaalt alleen wat GEWOON is. Een woord dat er niet op staat is per definitie een
    rariteit en hoort te vlaggen - een onvolledige lijst geeft ruis, nooit een gemiste vondst."""
    layers = [_layer(1.0, 2.0, "fijn zand met sporen van bentoniet")]

    found = lithology.notable_terms(layers)

    assert [term.word for term in found] == ["bentoniet"]
    assert found[0].depth == "1.00-2.00 m"
    assert found[0].quote == "fijn zand met sporen van bentoniet"


def test_the_terms_he_named_stay_flagged_however_the_list_grows():
    """Concreties, zandsteen, glauconiet, veen en puin vlaggen in elke vorm, ook als iemand de
    lijst van gewone woorden uitbreidt."""
    layers = [_layer(0.0, 1.0, "zand met zandsteenconcreties"),
              _layer(1.0, 2.0, "zand, sterk glauconiethoudend"),
              _layer(2.0, 3.0, "bruine veenhoudende leem"),
              _layer(3.0, 4.0, "zand, sterk baksteenhoudend")]

    words = [term.word for term in lithology.notable_terms(layers)]

    assert words == ["zandsteenconcreties", "glauconiethoudend", "veenhoudende",
                     "baksteenhoudend"]


def test_shells_in_an_admixture_are_ordinary_but_a_bed_is_not():
    """Schelpen in bijmenging zijn de gewone Vlaamse ondergrond; een schelpenbank is een ding
    waar je op stuit. In de 3630 gemeten lagen bestaat geen samenstelling "schelpenbank": de bank
    wordt met een eigen woord genoemd, en dat woord vlagt."""
    admixture = [_layer(0.0, 2.0, "fijn zand, silthoudend, zeer weinig schelpgruis"),
                 _layer(2.0, 3.0, "grijs zand met schelpen")]
    bed = [_layer(3.0, 4.0, "laag van verbrijzelde schelpen"),
           _layer(4.0, 5.0, "bruinzwarte coherente bank")]

    assert lithology.notable_terms(admixture) == []
    assert "bank" in [term.word for term in lithology.notable_terms(bed)]


def test_a_denied_material_is_not_reported_as_present():
    """"geen kalk" meldt juist dat er geen kalk is; dat als vondst afdrukken is een onwaarheid."""
    layers = [_layer(0.0, 1.0, "Fijner geelgroenachtig zand, geen kalk")]

    assert lithology.notable_terms(layers) == []


def test_a_coded_layer_holds_codes_and_is_left_alone():
    """Een laag uit de gecodeerde lithologie leest "FZ (groenbruin) bijmenging: SI/M, GL/N": codes,
    geen waarnemingen. Die doorzoeken levert alleen "bijmenging" op, honderd keer."""
    layers = [_layer(0.0, 0.5, "FZ (groenbruin) bijmenging: SI/M, GL/N", kind="gecodeerd")]

    assert lithology.notable_terms(layers) == []


def test_a_word_is_named_once_at_the_depth_it_starts():
    """Glauconiet in twintig lagen is één waarneming, niet twintig; wat de lezer nodig heeft is
    waar het begint."""
    layers = [_layer(0.0, 1.0, "zand"),
              _layer(1.0, 2.0, "zand, glauconiethoudend"),
              _layer(2.0, 3.0, "zand, glauconiethoudend"),
              _layer(3.0, 4.0, "zand, glauconiethoudend")]

    found = lithology.notable_terms(layers)

    assert len(found) == 1 and found[0].depth == "1.00-2.00 m"


def test_the_summary_line_names_every_word_with_its_depth():
    layers = [_layer(0.0, 0.2, "Straatsteen"), _layer(2.6, 4.2, "veenhoudende leem")]

    assert lithology.summarise(lithology.notable_terms(layers)) == \
        "straatsteen (0.00-0.20 m); veenhoudende (2.60-4.20 m)"


def test_the_french_of_the_old_records_is_ordinary_too():
    """De helft van de oude beschrijvingen staat in het Frans; zonder die woorden vlagt elke
    vooroorlogse boring op elke laag."""
    layers = [_layer(0.0, 3.0, "sable fin gris avec un peu d'argile, très homogène")]

    assert lithology.notable_terms(layers) == []


def test_filler_is_widened_away_but_the_rarity_beside_it_still_flags():
    """Verbreed de lijst van gewone woorden uit de frequentietabel, versmal de vlagregel nooit:
    een bindwoord, een kleur, een boornotitie of hoe dicht het zand gepakt zat is geen rariteit -
    de zandsteenconcretie in dezelfde zin blijft wel vlaggen."""
    layers = [_layer(0.0, 2.5, "dicht gepakt bruin zand, ongeveer horizontaal, "
                               "licht cremebruin, staal gewassen door de boormeester"),
              _layer(2.5, 3.0, "zand met zandsteenconcreties")]

    found = lithology.notable_terms(layers)

    assert [term.word for term in found] == ["zandsteenconcreties"]
