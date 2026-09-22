"""Het pixelwerk van de schil: wat er op een plaatje staat en waar het gesneden mag worden.

Geen papier, geen layout - een legendagrafiek is een legendagrafiek, wat voor blad er later ook
onder komt. De plaatjes worden hier gebouwd zoals de diensten ze leveren (zie de conftest), want
dat is het enige wat deze functies te lezen krijgen. Waar de opmaak van een echte tekening de
vraag is, staat ze als fixture in `fixtures/`: een nagebouwde tekening bewijst niets over een
dienst die haar kaartbladen niet gelijk opmaakt."""
from __future__ import annotations

from pathlib import Path

from tests.qgis.conftest import dhmv_legend, drawn_png, inset_legend, pixels
from tests.qgis.conftest import write_png as _png

FIXTURES = Path(__file__).parent / "fixtures"
# De rij waarop de horizontale lijn staat die de profieltypekop van de eenhedentabel scheidt,
# gemeten op deze drie echte tekeningen (2026-09-22). Twee kaartbladen, twee opmaken: zie de
# README naast de bestanden.
RULE_ROWS = {"quartair_22010.png": 145, "quartair_07020.png": 189, "quartair_07029.png": 189}
TITLE_ROWS = 60  # tot hier reikt het woord "Profieltype"; alles eronder is de legenda zelf


def _inked(image, first, last):
    """Hoeveel rijen tussen `first` en `last` iets getekend hebben staan - wit en doorzichtig
    tellen niet mee. Zo valt te zeggen of er onder de titelregel nog iets stond."""
    return sum(any(image.pixelColor(column, row).alpha() != 0
                   and image.pixelColor(column, row).value() < 200
                   for column in range(image.width()))
               for row in range(first, min(last, image.height())))


def test_a_drawing_that_cannot_be_read_gives_no_strip(qgs_app, tmp_path):
    """Een bestand dat geen afbeelding is, levert geen kopstrook en zegt dat in het log - het mag
    geen leeg kader op de legendapagina worden."""
    from desktopstudie.core.logging_util import Log
    from desktopstudie.qgis import images

    kapot = tmp_path / "legendas" / "quartair_22026.png"
    kapot.parent.mkdir(parents=True, exist_ok=True)
    kapot.write_bytes(b"dit is geen png")
    lines = []

    assert images.crop_profile_header(kapot, Log("layout", lines.append, scope="qgis")) is None
    assert images.crop_sheet_units(kapot, "22", Log("layout", lines.append, scope="qgis")) is None
    assert sum("WARNING" in line for line in lines) == 2, lines


def test_a_drawing_without_a_white_band_falls_back_to_a_fixed_strip(qgs_app, tmp_path):
    """Zonder witte band is er geen natuurlijke snede. Dan wint een vaste strook: nog altijd een
    strook, en niet een heel blad eenhedentabel."""
    from qgis.PyQt.QtGui import QImage

    from desktopstudie.qgis import images

    vol = drawn_png(tmp_path / "vol.png", 980, 703)

    assert images.header_rows(QImage(str(vol))) == images.HEADER_FALLBACK_ROWS


def test_a_drawing_shorter_than_the_fallback_keeps_its_own_height(qgs_app, tmp_path):
    """Een tekening die korter is dan de vaste strook wordt niet langer gemaakt dan ze is."""
    from qgis.PyQt.QtGui import QImage

    from desktopstudie.qgis import images

    klein = drawn_png(tmp_path / "klein.png", 200, 40)

    assert images.header_rows(QImage(str(klein))) == 40


def test_de_kop_eindigt_op_de_horizontale_lijn_naar_de_eenhedentabel(qgs_app):
    """De betrouwbare markering is de horizontale lijn die de profieltypekop van de eenhedentabel
    scheidt. Gemeten op de drie echte tekeningen: 22010 rij 145 van 703, 07020 en 07029 rij 189
    van 1200, elk precies waar de kop eindigt."""
    from desktopstudie.qgis import images

    for naam, lijn in RULE_ROWS.items():
        assert images.header_rows(pixels(FIXTURES / naam)) == lijn, naam


def test_een_kopstrook_zegt_meer_dan_het_woord_profieltype(qgs_app):
    """"Bevat alleen het woord Profieltype - geen kleurvlak, geen code, geen omschrijving": dat
    is wat de kopstrook van kaartblad 07 de lezer zei. De strook hoort te dragen wat eronder
    staat, dus staat er op elke tekening inkt tot ver onder de titelregel."""
    from desktopstudie.qgis import images

    for naam in RULE_ROWS:
        tekening = pixels(FIXTURES / naam)
        strook = tekening.copy(0, 0, tekening.width(), images.header_rows(tekening))

        assert _inked(strook, TITLE_ROWS, strook.height()) > 30, naam


def test_het_kleurvlak_met_de_code_staat_op_de_strook_van_kaartblad_07(qgs_app):
    """Op kaartblad 07 is de code een cijfer in een klein gekleurd vlakje, en dat vlakje begint
    pas onder de titelregel. Een snede die daar bovenlangs gaat laat de lezer een strook zonder
    kleur en zonder code."""
    from desktopstudie.qgis import images

    for naam in ("quartair_07020.png", "quartair_07029.png"):
        tekening = pixels(FIXTURES / naam)
        strook = tekening.copy(0, 0, tekening.width(), images.header_rows(tekening))
        assert any(strook.pixelColor(kolom, rij).saturation() > 60
                   for rij in range(TITLE_ROWS, strook.height())
                   for kolom in range(strook.width())), naam


def test_de_kop_en_de_eenhedentabel_snijden_op_dezelfde_rij(qgs_app, tmp_path):
    """De eenhedentabel wordt aan de andere kant van dezelfde snede geknipt. Samen zijn ze weer de
    hele tekening, en de tabel begint met de lijn zelf - op beide opmaken."""
    from desktopstudie.qgis import images

    for naam in ("quartair_22010.png", "quartair_07020.png"):
        tekening = tmp_path / naam
        tekening.write_bytes((FIXTURES / naam).read_bytes())

        kop = images.crop_profile_header(tekening)
        tabel = images.crop_sheet_units(tekening, naam.split("_")[1][:2])

        geheel, strook, eenheden = pixels(tekening), pixels(kop), pixels(tabel)
        assert strook.height() + eenheden.height() == geheel.height(), naam
        assert strook.height() == RULE_ROWS[naam], naam
        assert images.rule_row(eenheden) == 0, f"{naam}: de tabel begint met haar eigen bovenrand"


def test_zonder_lijn_valt_de_snede_terug_op_de_witte_band(qgs_app, tmp_path):
    """De oude zoeker naar de eerste volledig witte rij blijft staan als terugval. Tekent de
    dienst haar tabel ooit zonder lijn erboven, dan is een snede in de witte band er nog altijd
    beter dan een heel blad eenhedentabel op de kaartpagina."""
    from qgis.PyQt.QtGui import QColor, QImage, QPainter

    from desktopstudie.qgis import images

    tekening = QImage(980, 400, QImage.Format.Format_ARGB32)
    tekening.fill(QColor(255, 255, 255))
    verf = QPainter(tekening)
    verf.fillRect(0, 0, 120, 24, QColor(0, 0, 0))              # "Profieltype"
    verf.fillRect(0, 34, 130, 60, QColor(200, 198, 170))       # kleurvlak en omschrijving
    verf.fillRect(0, 110, 980, 290, QColor(170, 170, 170))     # een tabel zonder lijn erboven
    verf.end()

    assert images.rule_row(tekening) is None
    assert images.header_rows(tekening) == 94


def test_the_colour_bar_of_a_legend_graphic_is_cut_out_and_laid_on_its_side(qgs_app, tmp_path):
    """Het strookje onder de kaart draagt de kleuren van de dienst zelf: het verloop wordt uit de
    GetLegendGraphic geknipt en een kwartslag gedraaid, met de laagste waarde links."""
    from qgis.PyQt.QtGui import QImage

    from desktopstudie.qgis import images

    source = dhmv_legend(tmp_path / "legendas" / "dhmv_dtm.png")

    strip = images.ramp_strip(source, tmp_path / "legendas" / "dhmv_dtm_schaal.png")

    assert strip is not None and strip.exists()
    image = QImage(str(strip))
    assert image.width() > image.height(), "liggend, want het gaat onder de kaart"
    left, right = image.pixelColor(0, image.height() // 2), image.pixelColor(image.width() - 1,
                                                                            image.height() // 2)
    assert left.green() > left.red(), "links het groen van de laagste waarde"
    assert right.red() > right.green(), "rechts het bruin van de hoogste"


def test_a_legend_graphic_without_a_colour_bar_gives_no_strip(qgs_app, tmp_path):
    """Verandert de dienst haar legenda van vorm, dan komt er geen strookje - liever geen
    kleurschaal dan een strook die niet bij de kaart hoort."""
    from desktopstudie.qgis import images

    plain = _png(tmp_path / "legendas" / "plat.png", 4, 4)
    from qgis.PyQt.QtGui import QColor, QImage
    image = QImage(60, 20, QImage.Format.Format_RGB32)
    image.fill(QColor(255, 255, 255))
    assert image.save(str(plain))

    assert images.ramp_strip(plain, tmp_path / "legendas" / "plat_schaal.png") is None


def test_a_colour_bar_that_does_not_touch_the_edge_is_still_found(qgs_app, tmp_path):
    """De GxG-legenda zet haar balk een pixel van de rand. Een zoeker die alleen naar kolom nul
    kijkt, vindt hem niet en het rapport zou de kaart zonder legenda laten."""
    from desktopstudie.qgis import images

    source = inset_legend(tmp_path / "legendas" / "gxg.png")

    rect = images.ramp_rect(pixels(source))

    assert rect is not None
    x, _y, width, height = rect
    assert x == 1 and width == 20 and height > 90


def test_a_bar_whose_smallest_value_is_on_top_is_turned_the_other_way(qgs_app, tmp_path):
    """Het hoogtemodel zet zijn hoogste waarde bovenaan, de grondwaterdiepte haar kleinste. Beide
    horen op papier van klein links naar groot rechts te lopen, dus draait de ene andersom."""
    from desktopstudie.qgis import images

    source = inset_legend(tmp_path / "legendas" / "gxg.png")

    plain = images.ramp_strip(source, tmp_path / "legendas" / "plain.png")
    flipped = images.ramp_strip(source, tmp_path / "legendas" / "flip.png", flip=True)

    left_plain = pixels(plain).pixelColor(0, 2)
    left_flipped = pixels(flipped).pixelColor(0, 2)
    assert left_plain.blue() == left_flipped.blue()
    assert left_plain.red() < left_flipped.red(), "gedraaid staat de bovenkant van de bron links"
