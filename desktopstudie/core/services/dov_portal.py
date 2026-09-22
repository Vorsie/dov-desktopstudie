"""One quirk of DOV's document portal, kept apart.

The quartair profieltype drawings hang from a download link on
`datasets.omgeving.vlaanderen.be` that ends in `_png`. That link is supposed to redirect to the
file, but the portal (a DSpace installation) answers it with its own web page now and then -
HTTP 200, `text/html`, 320 kB of Angular. Observed live on 2026-09-16: the same URL had given the
PNG minutes earlier.

That page is not worthless: it carries the state of the web application inside it, and in there
stands the direct link to the file (`.../server/api/core/bitstreams/<uuid>/content`) WITH the name
of that file beside it. This module reads that link out, so the caller can follow it instead of
reporting the drawing as a failure.

Deliberately NOT a DSpace client: no search, no item, no bundles - one regex over the answer we
already have in hand. If the portal changes shape the regex finds nothing, the caller gets `None`
and everything keeps working as before (the drawing is reported as a source that did not come
back). See the debt list in CLAUDE.md.
"""
from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urlsplit

# DSpace's direct download link. The uuid is spelled out so that half a match does not count.
CONTENT_HREF = re.compile(r"https://[\w.-]+/server/api/core/bitstreams/[0-9a-f]{8}-[0-9a-f]{4}-"
                          r"[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/content")
# HTML may escape its quotes (&q; in Angular's transfer state), so the name is searched for bare:
# "DOV_Quartair_50000_22010.png" is in there literally whatever the quoting does.
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def file_name_of(url: str) -> str:
    """The file name a download link asks for: `..._22010_png` is `DOV_..._22010.png`.

    The link ends in a handle - dots strung together, with the file name as its last piece and an
    underscore where that name has a dot
    (`be.vlaanderen...geo.<uuid>.DOV_Quartair_50000_22010_png`). The page names the file as it is
    on disk, so without this translation it never matches.
    """
    last = urlsplit(url).path.rsplit("/", 1)[-1]
    if last.endswith("_png"):
        return last.rsplit(".", 1)[-1][:-4] + ".png"
    return last


# What a portal page says when the document asked for is not there. Read off the CONTENT and not
# off the HTTP status: DSpace answers 200 on a "not found" page, so the status says nothing.
NOT_FOUND_MARKS = ("not found", "404", "niet gevonden", "does not exist")


def says_not_found(page: bytes) -> bool:
    """Whether this portal page says there is nothing to find.

    The difference is for the reader: "DOV publishes no drawing for this one" is a fact about the
    source, while "drawing not fetched" sounds like something a second attempt would fix. A page
    with a download link in it is never a not-found page, however often the word appears on it.
    """
    if page.startswith(PNG_MAGIC):
        return False
    text = page.decode("utf-8", "replace").lower()
    if CONTENT_HREF.search(text):
        return False
    return any(mark in text for mark in NOT_FOUND_MARKS)


def content_link(page: bytes, url: str) -> Optional[str]:
    """The direct link to the file `url` asks for, read out of the portal page itself.

    `None` the moment anything is off: the answer is not a page at all (a PNG, say), the page does
    not name the file that was asked for - then it is about something else and the link would
    yield the wrong file - or there is no download link on it. Nothing beats the wrong file.
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
    # One page carries one file in practice; where there are more, the link nearest the name that
    # was asked for wins - in the page's JSON a link and a name belong to the same object.
    best = min(links, key=lambda m: min(abs(m.start() - pos) for pos in names))
    return best.group(0)
