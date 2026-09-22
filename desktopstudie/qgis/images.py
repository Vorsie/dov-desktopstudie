"""Pixel work on the pictures a report uses: reading them, cutting them and stacking them.

Nothing here knows anything about paper. A millimetre, a margin and a page do not occur in this
module; every function takes a `QImage` (or the path of one) and answers in pixels or in a file
on disk. That is what makes it separable from `layout.py`, and it is also what makes it testable
without a layout: a legend graphic is a legend graphic whatever sheet it later lands on.

Three kinds of question are asked here.

*What is this picture made of?* `ramp_rect` finds the colour band inside a legend graphic and
`header_rows` finds where a profile-type drawing stops being a header - both by reading the pixels,
because neither service documents its own layout and both have moved before.

*Cut it.* `ramp_strip`, `crop_profile_header` and `crop_sheet_units` write the piece that is
wanted as a file of its own, so the layout only ever places a picture and never crops one.

*Is there anything on it?* `is_empty` answers the coverage question for a GetMap for free, and
`blank_rows` / `cut_row` say where a tall legend may be broken without cutting through an entry.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, List, Optional, Sequence, Tuple

from qgis.PyQt.QtGui import QImage, QPainter, QTransform

from ..core.paths import safe_segment

# A colour ramp is a solid band against the left edge of its legend graphic. Less than this is a
# swatch, not a ramp, and then no strip is cut at all - see `ramp_rect`.
RAMP_MIN_ROWS = 10
RAMP_MIN_COLUMNS = 4
WHITE_RGB = bytes((255, 255, 255))
# The quartair profile-type drawings land next to the map legends, under their own prefix so a
# second run overwrites the file of the same profile type instead of collecting copies.
ZONE_LEGEND_PREFIX = "quartair_"
ZONE_LEGEND_SHEET = "kaartblad_"
HEADER_SUFFIX = "_kop"
# A DOV profile-type drawing starts with the type itself - colour swatch, letter code and one line
# of description - and continues with the units table of the whole map sheet. The two are separated
# by a white band, and the first white row BELOW the swatch is the cut. Above HEADER_MIN_ROWS there
# is another white band (under the word "Profieltype"), which is why the search starts there.
HEADER_MIN_ROWS = 60
HEADER_FALLBACK_ROWS = 110


def ramp_rect(image: QImage) -> Optional[Tuple[int, int, int, int]]:
    """The colour-ramp band inside a legend graphic: (x, y, width, height), or None.

    A ramp legend is drawn as one solid band against the LEFT edge, its title above it and its
    range printed beside it - that is what the DHMV service answers (102 x 68 px, a band of
    16 x 48, live 2026-09-17). So the rows that BEGIN with a run of one colour are the band, and
    the narrowest of those runs is its width.

    None for a legend shaped any other way, and then the report prints no colours at all: a strip
    whose colours are not the map's is worse than no strip.
    """
    rgba = image.convertToFormat(QImage.Format.Format_ARGB32)
    width, height, stride = rgba.width(), rgba.height(), rgba.bytesPerLine()
    buffer = rgba.constBits()
    buffer.setsize(height * stride)
    data = bytes(buffer)
    # Per row: where its solid run of one colour starts and how long it is. Not "column zero":
    # the GxG legend leaves a white pixel against the edge, and a search that insists on the very
    # first column finds nothing there and leaves that map without a legend.
    bands: List[Tuple[int, int]] = []
    for y in range(height):
        row = data[y * stride:y * stride + width * 4]
        start, run = 0, 0
        while start < width:
            pixel = row[start * 4:start * 4 + 4]
            if pixel[3] != 0 and pixel[:3] != WHITE_RGB:
                run = 1
                while start + run < width and row[(start + run) * 4:(start + run) * 4 + 4] == pixel:
                    run += 1
                break
            start += 1
        bands.append((start, run) if run >= RAMP_MIN_COLUMNS else (-1, 0))
    best_top, best_rows, best_start = 0, 0, -1
    top = None
    for y, (start, _run) in enumerate(bands + [(-1, 0)]):
        # One band: the rows have to open at the same column, or a stack of legend swatches would
        # read as one long bar.
        if start >= 0 and (top is None or bands[top][0] == start):
            top = y if top is None else top
            continue
        if top is not None and y - top > best_rows:
            best_top, best_rows, best_start = top, y - top, bands[top][0]
        top = y if start >= 0 else None
    if best_rows < RAMP_MIN_ROWS:
        return None
    return (best_start, best_top,
            min(run for _start, run in bands[best_top:best_top + best_rows]), best_rows)


def ramp_strip(legend_png, target, flip: bool = False) -> Optional[Path]:
    """The colour band of a legend graphic, cut out, laid on its side and saved as `target`.

    The band runs high-to-low downwards (the DTM is brown at 300 mTAW on top, green at -50 at the
    bottom) while a reader expects a horizontal scale to run low on the left. So it is turned a
    quarter clockwise, which puts the top of the band on the right. Turning and stretching change
    no colour - which is the whole point: what lands under the map is the service's own ramp.
    """
    image = QImage(str(legend_png))
    if image.isNull():
        return None
    rect = ramp_rect(image)
    if rect is None:
        return None
    # A quarter clockwise puts the TOP of the band on the right, which is where the height model
    # wants its maximum. A bar whose smallest value sits on top turns the other way, so that both
    # read small-left to large-right (`MapEntry.ramp_low_at_top`).
    band = image.copy(*rect).transformed(QTransform().rotate(-90 if flip else 90))
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    return target if band.save(str(target)) else None


def header_rows(image: QImage) -> int:
    """How many pixel rows of a profile-type drawing are its header.

    The answer is the first fully white row under the colour swatch: that band is the gap before
    "Eenheden op kaartblad <nn>". A drawing without such a band falls back to a fixed strip, which
    is still a strip rather than a whole sheet of units table.
    """
    flags = blank_rows(image)
    for row in range(min(HEADER_MIN_ROWS, len(flags)), len(flags)):
        if flags[row]:
            return row
    return min(HEADER_FALLBACK_ROWS, image.height())


def _cropped(path, target: Path, part: Callable[[QImage], Tuple[int, int, int, int]],
             what: str, log=None) -> Optional[Path]:
    """One rectangle out of a profile-type drawing, saved as `target`.

    The two crops below differ in exactly two things - which rectangle and what the failure is
    called - so the reading, the null check and the save live here. `part` gets the image and
    answers (x, y, width, height), because both rectangles need `header_rows` on the loaded image.
    """
    image = QImage(str(path))
    if image.isNull():
        if log:
            log.warning(f"Profieltypetekening niet leesbaar: {path}")
        return None
    if not image.copy(*part(image)).save(str(target)):
        if log:
            log.warning(f"{what} niet weggeschreven: {target}")
        return None
    return target


def crop_sheet_units(path, sheet: str, log=None) -> Optional[Path]:
    """The same drawing WITHOUT its profile-type header, as `quartair_kaartblad_<nn>.png`.

    The units table underneath is valid for every profile type of the sheet. Left on, the header of
    whichever type happened to be fetched first sits above it and the table reads as that one
    type's. The source line under the table is part of the drawing and stays.
    """
    # The sheet is the first two characters of a WFS profile-type code, so it is external text
    # and ".." is two characters: `with_name("..")` would write into the parent folder. A sheet
    # that leaves no name behind gets no units page, which is what every other failure here does.
    try:
        named = safe_segment(sheet)
    except ValueError as exc:
        if log:
            log.warning(f"Eenhedentabel overgeslagen: {exc}")
        return None
    target = Path(path).with_name(f"{ZONE_LEGEND_PREFIX}{ZONE_LEGEND_SHEET}{named}.png")
    return _cropped(path, target,
                    lambda image: (0, header_rows(image), image.width(),
                                   image.height() - header_rows(image)),
                    "Eenhedentabel", log)


def crop_profile_header(path, log=None) -> Optional[Path]:
    """Cut the header strip off a profile-type drawing and save it beside it as `<name>_kop.png`.

    What is left out is the units table of the map sheet, which is the same drawing for every
    profile type of that sheet: printed once per type it would be the same page three times over.
    """
    target = Path(path).with_name(Path(path).stem + HEADER_SUFFIX + ".png")
    return _cropped(path, target, lambda image: (0, 0, image.width(), header_rows(image)),
                    "Kopstrook", log)


def load_tile(data: bytes) -> Optional[QImage]:
    """The bytes of a GetMap as an image, or None when the service sent something else."""
    image = QImage()
    return image if data and image.loadFromData(data) else None


def over_backdrop(theme: QImage, backdrop: QImage, opacity: float) -> QImage:
    """The theme painted over the base map, at the opacity the catalogue gives the theme.

    Both come from the same box at the same pixel size, so they line up by construction - the
    page draws ONE picture and nothing has to be registered afterwards.
    """
    canvas = backdrop.convertToFormat(QImage.Format.Format_ARGB32)
    painter = QPainter(canvas)
    painter.setOpacity(opacity)
    painter.drawImage(0, 0, theme)
    painter.end()
    return canvas


def is_empty(image: QImage) -> bool:
    """True when every pixel is the same, or every pixel is fully transparent.

    That is what a mosaic without a sheet for this place answers: HTTP 200 and nothing drawn.
    """
    rgba = image.convertToFormat(QImage.Format.Format_ARGB32)
    buffer = rgba.constBits()
    buffer.setsize(rgba.height() * rgba.bytesPerLine())
    data, stride, row_bytes = bytes(buffer), rgba.bytesPerLine(), rgba.width() * 4
    pixels = b"".join(data[y * stride:y * stride + row_bytes] for y in range(rgba.height()))
    if not pixels:
        return True
    first = pixels[:4]
    return (all(pixels[i:i + 4] == first for i in range(0, len(pixels), 4))
            or all(pixels[i + 3] == 0 for i in range(0, len(pixels), 4)))


def blank_rows(image: QImage) -> List[bool]:
    """One flag per pixel row: True where the row is entirely white or entirely transparent.

    Those rows are the gaps between legend entries, and they are where a page break belongs. The
    whole mask is built in one pass over the raw buffer: a legend is a few thousand rows and
    reading it pixel by pixel through `pixelColor` takes seconds.
    """
    rgba = image.convertToFormat(QImage.Format.Format_ARGB32)
    width, height, stride = rgba.width(), rgba.height(), rgba.bytesPerLine()
    buffer = rgba.constBits()
    buffer.setsize(height * stride)
    data = bytes(buffer)
    white, clear = b"\xff" * (width * 4), b"\x00" * (width * 4)
    flags: List[bool] = []
    for y in range(height):
        row = data[y * stride:y * stride + width * 4]
        # The two fast paths cover a solid white row and a fully transparent one, which is what a
        # gap in a GetLegendGraphic image actually is; the loop is only for mixed rows.
        flags.append(row == white or row == clear
                     or all(row[i + 3] == 0 or row[i:i + 3] == b"\xff\xff\xff"
                            for i in range(0, len(row), 4)))
    return flags


def cut_row(flags: Sequence[bool], top: int, nominal: int) -> int:
    """Where to break a strip that would nominally end at `nominal`: the nearest blank row above
    it, so the break lands in the gap between two legend entries instead of through one.

    Falls back to the nominal break when the slice holds no blank row at all - a legend without
    any gap has nothing to protect, and a break that never happens fits on no page.
    """
    for row in range(nominal, top, -1):
        if flags[row - 1]:
            return row
    return nominal
