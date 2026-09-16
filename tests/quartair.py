"""The quartair test data the core, the layout and the pipeline tests all need.

Three files were carrying their own copy of the same legend URL template and the same row builder,
which is two copies too many: the day the WFS renames a field, one of them keeps passing.
"""
from __future__ import annotations

LEGEND_URL = ("https://datasets.omgeving.vlaanderen.be/be.vlaanderen.omgeving.distribution.geo."
              "e58c3358-e149-42b6-9229-c3a9ac88c3d4.DOV_Quartair_50000_{code}_png")
TITLE = "Quartairgeologische kaart 1/50 000 (samengesteld)"


def legend_url(code: str) -> str:
    """The drawing URL the WFS hands out for one profile type."""
    return LEGEND_URL.format(code=code)


def rows(codes):
    """The rows as the WFS gives them: one per map polygon, so a code can repeat."""
    return [{"profieltype": code, "legende": legend_url(code)} for code in codes]


def map_fact(codes=("22026", "22010", "22026", "22098")):
    """A MapFact for the composite quartair map, built from those rows."""
    from desktopstudie.core.model import MapFact

    return MapFact("quartair", TITLE, rows(codes))
