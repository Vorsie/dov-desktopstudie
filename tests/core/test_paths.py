"""Tekst die van buiten komt mag nooit zelf bepalen WAAR een bestand landt.

Een permkey, een profieltypecode en een kaartbladnummer komen alle drie uit een DOV-antwoord.
Ze worden een stuk van een bestandsnaam, en een antwoord met een schuine streep erin is dan geen
naam meer maar een pad.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from desktopstudie.core import paths


def _stays_inside(value: str, folder: Path) -> bool:
    """Of een naam die uit `safe_segment` komt de map waarin hij hoort niet kan verlaten.

    Gemeten zoals het misgaat - de naam wordt aan een map geplakt en het pad wordt opgelost -
    en niet op de vorm van de string: `.._.._ergens` ziet eruit als een pad en is er geen.
    """
    joined = (folder / paths.safe_segment(value)).resolve()
    return joined.parent == folder.resolve()


def test_a_value_with_a_slash_in_it_cannot_leave_its_folder(tmp_path):
    """`../../ergens` is een pad, geen naam. De scheidingstekens vallen weg, er blijft één stuk
    over, en aan de figurenmap geplakt landt het IN die map."""
    for hostile in ("../../ergens", r"..\..\ergens", "/etc/passwd", "C:/Windows/system32",
                    "..%2F..%2Fergens", "map/onder/erin"):
        assert _stays_inside(hostile, tmp_path), hostile


def test_an_ordinary_permkey_is_left_alone():
    """De gewone gevallen mogen niet veranderen: een figuurnaam die per run verspringt maakt elke
    vorige studie onvindbaar."""
    assert paths.safe_segment("1965-039716") == "1965-039716"
    assert paths.safe_segment("2024-090319") == "2024-090319"
    assert paths.safe_segment("g3dv3_F") == "g3dv3_F"
    assert paths.safe_segment("22026") == "22026"


def test_a_value_that_leaves_nothing_usable_is_refused():
    """Leeg, "." en ".." zijn geen bestandsnamen. Er is dan niets om te schrijven, en een naam
    verzinnen zou het bestand ergens neerzetten waar niemand het zoekt."""
    for hopeless in ("", "   ", ".", "..", "...", "/", "///", "___"):
        with pytest.raises(ValueError):
            paths.safe_segment(hopeless)


def test_a_fallback_is_used_instead_of_refusing():
    """Waar een mens de tekst typt - de projectnaam in de dialoog - hoort een onbruikbare invoer
    geen uitzondering te geven maar de standaardnaam."""
    assert paths.safe_segment("///", fallback="studie") == "studie"
    assert paths.safe_segment("Gent Zuid", fallback="studie") == "Gent_Zuid"


def test_letters_with_accents_survive():
    """Een projectnaam met een accent hoort haar accent te houden: dat is een letter, geen
    scheidingsteken."""
    assert paths.safe_segment("Café") == "Café"
