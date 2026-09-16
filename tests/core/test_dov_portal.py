"""Het documentportaal van DOV stuurt op de downloadlink soms zijn eigen webpagina (HTTP 200).

De regel: als het portaal zijn webpagina stuurt in plaats van het bestand, wijst die pagina zelf
naar het bestand - en die link volgen we. Een pagina die over een ander bestand gaat, of die geen
downloadlink bevat, levert niets op; dan is de tekening echt niet op te halen.
"""
from pathlib import Path

from desktopstudie.core.services.dov_portal import content_link

FIXTURES = Path(__file__).parent / "fixtures"
URL_22010 = ("https://datasets.omgeving.vlaanderen.be/be.vlaanderen.omgeving.distribution.geo."
             "e58c3358-e149-42b6-9229-c3a9ac88c3d4.DOV_Quartair_50000_22010_png")
URL_22026 = URL_22010.replace("22010", "22026")


def portal_page() -> bytes:
    return (FIXTURES / "dov_portal_pagina_22010.html").read_bytes()


def test_de_pagina_wijst_zelf_naar_het_bestand():
    link = content_link(portal_page(), URL_22010)

    assert link == ("https://datasets-services.omgeving.vlaanderen.be/server/api/core/bitstreams/"
                    "0082d459-f86d-4a5b-9508-bbb98ae38e88/content")


def test_een_pagina_over_een_ander_bestand_geeft_geen_link():
    assert content_link(portal_page(), URL_22026) is None


def test_een_pagina_zonder_downloadlink_geeft_geen_link():
    page = b"<!DOCTYPE html><html><body>DOV_Quartair_50000_22010.png</body></html>"

    assert content_link(page, URL_22010) is None


def test_de_png_zelf_is_geen_pagina_om_in_te_lezen():
    assert content_link(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64, URL_22010) is None


def test_van_twee_bestanden_wint_de_link_bij_de_juiste_naam():
    other = ("https://datasets-services.omgeving.vlaanderen.be/server/api/core/bitstreams/"
             "11111111-1111-4111-8111-111111111111/content")
    wanted = ("https://datasets-services.omgeving.vlaanderen.be/server/api/core/bitstreams/"
              "22222222-2222-4222-8222-222222222222/content")
    page = (f'<html>{other}"_name":"DOV_Quartair_50000_99999.png"'
            f'{wanted}"_name":"DOV_Quartair_50000_22010.png"</html>').encode()

    assert content_link(page, URL_22010) == wanted
