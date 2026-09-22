"""Tekst die van buiten komt mag nooit zelf bepalen WAAR een bestand landt.

Een permkey, een profieltypecode en een kaartbladnummer komen alle drie uit een DOV-antwoord.
Ze worden een stuk van een bestandsnaam, en een antwoord met een schuine streep erin is dan geen
naam meer maar een pad.
"""
from __future__ import annotations

import pytest

from desktopstudie.core import paths


def test_a_value_with_a_slash_in_it_cannot_become_a_path():
    """`../../ergens` is een pad, geen naam: de scheidingstekens vallen weg, het resultaat is één
    stuk en het kan de map waarin het hoort niet meer verlaten."""
    cleaned = paths.safe_segment("../../ergens")

    assert "/" not in cleaned and "\\" not in cleaned
    assert not cleaned.startswith("..")


def test_a_windows_path_and_a_percent_escape_go_the_same_way():
    assert "\\" not in paths.safe_segment(r"..\..\ergens")
    assert "/" not in paths.safe_segment("..%2F..%2Fergens").replace("%", "")


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
