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


def test_an_abbreviation_is_not_printed_as_a_three_letter_fragment():
    """"Num. planulatus" is de afkorting van Nummulites. De tokeniser brak hem op de punt en zette
    "num" in het rapport van een klant - een brokstuk, geen waarneming. Een kort woord met een punt
    midden in de zin is een afkorting en wordt niet gedrukt; het glauconiet ernaast wel."""
    layers = [_layer(22.5, 25.0, "zeer fijn glauconiethoudend zand met Num. planulatus")]

    words = [term.word for term in lithology.notable_terms(layers)]

    assert "num" not in words
    assert words == ["glauconiethoudend"], "de soortnaam zelf is geen opmerking meer"


def test_a_word_that_ends_a_sentence_keeps_its_place():
    """Een punt die een zin afsluit hoort niet bij het woord: "glauconiethoudend." is een
    waarneming, geen afkorting, en mag niet met de brokstukken meeverdwijnen."""
    layers = [_layer(0.0, 1.0, "Fijn zand, glauconiethoudend. Daaronder leem.")]

    assert [term.word for term in lithology.notable_terms(layers)] == ["glauconiethoudend"]


def test_a_fossil_name_is_not_a_remark():
    """"nummulites planulatus shouldn't be flagged at all" - een soortnaam zegt in welke formatie
    je zit, niet dat je iets zult raken. De steenbrokken in dezelfde zin blijven wel een
    opmerking, en een boring die alleen soortnamen noemt levert geen regel op."""
    layers = [_layer(22.5, 25.0, "zand met Nummulites planulatus - Turbinolia, en steenbrokken")]

    found = lithology.notable_terms(layers)

    assert [term.word for term in found] == ["steenbrokken"]
    assert lithology.summarise(found) == "steenbrokken (22.50-25.00 m)"
    assert lithology.notable_terms(
        [_layer(20.0, 22.0, "grijs zand met talrijke Nummulites planulatus")]) == []


def test_a_shell_BED_still_fires_where_the_shells_themselves_do_not():
    """Schelpen in bijmenging zijn gewoon en soortnamen zijn dat nu ook, maar een BANK blijft een
    rariteit: die wordt gevangen door het woord dat haar aanduidt, niet door de soort erin."""
    beds = [_layer(0.0, 1.0, "laag van verbrijzelde schelpen met Pecten corneus, coherente bank")]

    assert [term.word for term in lithology.notable_terms(beds)] == ["bank"]


def test_a_short_word_that_closes_a_description_is_still_a_word():
    """Aan het einde van een beschrijving is er niets meer om een afkorting aan te herkennen, dus
    wordt er niet geraden: "gips.", "löss." en "grès." zijn waarnemingen van vier letters en
    blijven staan. Alleen een punt MIDDEN in de zin snijdt een woord af."""
    for material in ("gips", "löss", "grès"):
        layers = [_layer(0.0, 1.0, f"Grijze leem, onderaan {material}.")]
        assert [term.word for term in lithology.notable_terms(layers)] == [material]

    assert lithology.notable_terms(
        [_layer(0.0, 1.0, "zand met Num. mergel")])[0].word == "mergel", "de punt snijdt Num. af"


def test_a_word_that_merely_ends_in_geen_is_not_a_denial():
    """"geen kalk" ontkent kalk; "heterogeen puin" ontkent niets. De ontkenning werd op ruwe tekst
    getoetst, dus elk woord dat op "geen" eindigt wiste het woord erna - en "heterogeen" en
    "homogeen" staan zelf op de lijst van gewone woorden. Zo verdwenen puin en veen geruisloos,
    precies de richting die niet mag."""
    assert [t.word for t in lithology.notable_terms(
        [_layer(0.0, 1.0, "heterogeen puin met zand")])] == ["puin"]
    assert [t.word for t in lithology.notable_terms(
        [_layer(0.0, 1.0, "homogeen veen")])] == ["veen"]
    assert "baksteen" in [t.word for t in lithology.notable_terms(
        [_layer(0.0, 1.0, "bijzonder veel baksteen")])]
    assert lithology.notable_terms([_layer(0.0, 1.0, "zand, geen veen")]) == []


def test_a_material_denied_by_its_own_suffix_is_not_a_report_of_it():
    """"zandsteenvrij" meldt geen zandsteen, net zomin als "geen kalk" kalk meldt - en toch vlagde
    het, omdat de stam voorging op de lijst. Een achtervoegsel dat ontkent doet hetzelfde werk als
    een ontkenning ervoor. De korrels zelf blijven wel een waarneming van glauconiet."""
    assert lithology.notable_terms([_layer(0.0, 1.0, "fijn zand, zandsteenvrij")]) == []
    assert lithology.notable_terms([_layer(0.0, 1.0, "fijn zand, glauconietarm")]) == []
    assert [t.word for t in lithology.notable_terms(
        [_layer(0.0, 1.0, "fijn zand met glauconietkorrels")])] == ["glauconietkorrels"]


def test_gravel_as_an_admixture_is_ordinary():
    """"geel fijn zand met een weinig grind" - grind als bijmenging is gewone grond. Een grindLAAG
    of grindbank blijft wel een rariteit: die draagt haar eigen woord."""
    assert lithology.notable_terms(
        [_layer(0.0, 1.0, "geel fijn zand met een weinig grind")]) == []
    assert [t.word for t in lithology.notable_terms(
        [_layer(0.0, 1.0, "zand met een grindlaag")])] == ["grindlaag"]


def test_colours_adjectives_and_plant_debris_are_ordinary():
    """"kleuren niet vermelden, plantenresten ook niet roestkleurig ook niet, mooi schelpje? niet
    vermelden, schelpfragment, niet vermelden, paar?" - een beschrijving van gewone grond hoort
    geen enkele opmerking op te leveren."""
    assert lithology.notable_terms([_layer(0.0, 1.0,
        "donkerbruine en lichtbruine klei, fijnzandhoudend, met plantenresten, wortels, "
        "plastisch, weinig kalkhoudend")]) == []
    assert lithology.notable_terms([_layer(0.0, 1.0,
        "roestkleurige kleivlekken, een mooi schelpje, een schelpfragment, een paar "
        "verkleurende brosse plantenresten")]) == []


def test_what_a_geotechnician_still_has_to_see_keeps_flagging():
    """Wat hij wel wil zien blijft komen: silexkeien, veen in elke vorm, baksteen, steenbrokken."""
    for text, expected in (
            ("grijze klei met silexkeien", "silexkeien"),
            ("zand met veenbrokjes", "veenbrokjes"),
            ("aanvulling met baksteen", "baksteen"),
            ("zand met steenbrokken", "steenbrokken"),
            ("klei, veenhoudend", "veenhoudend")):
        words = [t.word for t in lithology.notable_terms([_layer(0.0, 1.0, text)])]
        assert expected in words, f"{text!r} gaf {words}"


def test_the_plain_words_of_kb28d96e_B87_are_ordinary_ground():
    """Een willekeurige run zette twaalf termen onder boring kb28d96e-B87. Zandleem, zavel, een
    bouwlaag, losser zand, kwartskorrels en zandlensjes zijn gewone grond - geen van zessen zegt
    een machinist iets wat hij nog niet wist. Wat hij wel moet zien blijft staan: turfballen en
    silexstukken."""
    plain = ("zwarte bruine zandleem bouwlaag, losser lemig zavel, kleiig grijs zeer fijn zand "
             "met zandlensjes en kwartskorrels")
    assert lithology.notable_terms([_layer(0.0, 1.0, plain)]) == []
    words = [t.word for t in lithology.notable_terms(
        [_layer(0.0, 1.0, "grijze leem met turfballen en silexstukken")])]
    assert "turfballen" in words and "silexstukken" in words


def test_a_formation_name_is_a_date_stamp_like_a_fossil_name():
    """"ieper. klei" op hetzelfde blad: de formatienaam staat al in de laagbeschrijving en zegt,
    net als een soortnaam, in welke formatie je staat - niet wat je zult tegenkomen. Ieperiaan,
    Aalter, Asse, Boom en Maldegem staan al aan de gewone kant; de afgekorte vorm hoort erbij."""
    assert lithology.notable_terms(
        [_layer(22.5, 25.0, "grijsgroenachtige harde ieper. klei")]) == []


def test_the_words_the_other_two_runs_flagged_are_ordinary_too():
    """Brasschaat en Brugge leverden dezelfde soort ruis: teeltaarde is de bouwvoor onder een
    andere naam, een zandfractie is zand, en normaal, brokkelig en substraat beschrijven gewone
    grond. Steenpuin en zandsteen in dezelfde beschrijvingen blijven staan."""
    assert lithology.notable_terms([_layer(0.0, 0.8, "Teeltaarde - bruin, normaal")]) == []
    assert lithology.notable_terms(
        [_layer(0.0, 1.0, "heterogene zware klei, bovenaan humeus, brokkelig")]) == []
    assert lithology.notable_terms(
        [_layer(1.2, 2.0, "roestig zand, witfijn zand, zandfractie op het substraat")]) == []
    words = [t.word for t in lithology.notable_terms(
        [_layer(0.0, 1.0, "steenpuin op groene klei met zandsteen")])]
    assert "steenpuin" in words and "zandsteen" in words


def test_one_sand_layer_is_as_ordinary_as_several():
    """"zandlaagje" bleef staan terwijl "zandlaagjes" allang gewone grond was: het enkelvoud hoort
    bij dezelfde regel, net als lensje bij lenzen."""
    assert lithology.notable_terms([_layer(1.5, 1.6, "klei met een zandlaagje")]) == []
