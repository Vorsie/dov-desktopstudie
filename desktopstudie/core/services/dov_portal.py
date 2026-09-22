"""Eén eigenaardigheid van het documentportaal van DOV, apart gehouden.

De Quartair-profieltypetekeningen hangen aan een downloadlink van
`datasets.omgeving.vlaanderen.be` die op `_png` eindigt. Die link hoort door te verwijzen naar het
bestand, maar het portaal (een DSpace-installatie) antwoordt er soms met zijn eigen webpagina op -
HTTP 200, `text/html`, 320 kB Angular. Live vastgesteld op 2026-09-16: dezelfde URL gaf minuten
eerder de PNG.

Die pagina is niet waardeloos: ze draagt de toestand van de webapplicatie in zich, en daarin staat
de directe link naar het bestand (`.../server/api/core/bitstreams/<uuid>/content`) mét de naam van
dat bestand. Deze module haalt die link eruit, zodat de beller hem kan volgen in plaats van de
tekening als mislukt te melden.

Dit is bewust géén DSpace-client: geen zoekopdracht, geen item, geen bundles - één regex op het
antwoord dat we tóch al binnen hebben. Verandert het portaal van vorm, dan vindt de regex niets,
krijgt de beller `None` en blijft alles werken zoals voordien (de tekening wordt als niet-opgehaalde
bron gemeld). Zie de schuldlijst in CLAUDE.md.
"""
from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urlsplit

# De directe downloadlink van DSpace. Het uuid staat er los in zodat een halve match niet telt.
CONTENT_HREF = re.compile(r"https://[\w.-]+/server/api/core/bitstreams/[0-9a-f]{8}-[0-9a-f]{4}-"
                          r"[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/content")
# HTML mag zijn aanhalingstekens ontsnappen (&q; in de transfer-state van Angular), dus de naam
# wordt kaal gezocht: "DOV_Quartair_50000_22010.png" staat er hoe dan ook letterlijk in.
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def file_name_of(url: str) -> str:
    """De bestandsnaam die een downloadlink vraagt: `..._22010_png` is `DOV_..._22010.png`.

    De link eindigt op een handle - punten aan elkaar geregen, met de bestandsnaam als laatste
    stuk en een liggend streepje waar die naam een punt heeft
    (`be.vlaanderen...geo.<uuid>.DOV_Quartair_50000_22010_png`). De pagina noemt de naam zoals ze
    op schijf staat, dus zonder deze vertaling matcht ze nooit.
    """
    last = urlsplit(url).path.rsplit("/", 1)[-1]
    if last.endswith("_png"):
        return last.rsplit(".", 1)[-1][:-4] + ".png"
    return last


# Wat een portaalpagina zegt als het gevraagde document er niet is. Op de inhoud gelezen en niet
# op de HTTP-status: DSpace antwoordt 200 op een "niet gevonden"-pagina, dus de status zegt niets.
NOT_FOUND_MARKS = ("not found", "404", "niet gevonden", "does not exist")


def says_not_found(page: bytes) -> bool:
    """Of deze portaalpagina meldt dat er niets te vinden is.

    Het verschil is voor de lezer: "DOV publiceert hiervoor geen tekening" is een feit over de
    bron, "tekening niet opgehaald" klinkt als iets dat een tweede poging verdient. Een pagina met
    een downloadlink erin is nooit een niet-gevonden-pagina, hoe vaak het woord er ook in staat.
    """
    if page.startswith(PNG_MAGIC):
        return False
    text = page.decode("utf-8", "replace").lower()
    if CONTENT_HREF.search(text):
        return False
    return any(mark in text for mark in NOT_FOUND_MARKS)


def content_link(page: bytes, url: str) -> Optional[str]:
    """De directe link naar het bestand dat `url` vraagt, gelezen uit de portaalpagina zelf.

    `None` zodra iets niet klopt: het antwoord is geen pagina (een PNG bijvoorbeeld), de pagina
    noemt de gevraagde bestandsnaam niet - dan gaat ze over iets anders en zou de link het verkeerde
    bestand opleveren - of er staat geen downloadlink in. Liever niets dan het verkeerde bestand.
    """
    if page.startswith(PNG_MAGIC):
        return None
    text = page.decode("utf-8", "replace")
    name = file_name_of(url)
    names = [m.start() for m in re.finditer(re.escape(name), text)]
    if not names:
        return None
    links = list(CONTENT_HREF.finditer(text))
    if not links:
        return None
    # Eén pagina draagt in de praktijk één bestand; staan er meer, dan wint de link die het dichtst
    # bij de gevraagde naam staat - in de JSON van de pagina horen link en naam bij hetzelfde object.
    best = min(links, key=lambda m: min(abs(m.start() - pos) for pos in names))
    return best.group(0)
