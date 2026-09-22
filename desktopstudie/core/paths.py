"""Turning text that came from somewhere else into ONE path segment.

Three values a study writes into a file name come straight out of a service answer: the permkey of
a sounding or a borehole (the last piece of a DOV URL), the quartair profile-type code and the map
sheet derived from it. None of them is validated by the service, and none of them has to be a
name: `../../ergens` is a path, and a path joined onto the figures folder does not stay in it.

It takes a hijacked DOV, or a broken TLS chain in front of it, for that to happen - but the fix is
one substitution and the alternative is a plugin that writes where a stranger tells it to.

The rule is an allowlist, the same direction as the lithology vocabulary: letters, digits, and the
three punctuation marks every file system accepts (`.`, `-`, `_`). Everything else collapses, and
what is left over has to be a name - a segment of nothing but separators, or one of the two that
mean a directory, is refused rather than guessed at.
"""
from __future__ import annotations

import re

# `\w` keeps unicode letters on purpose: a project name with an accent in it is a name, not a
# separator, and mangling it would rename the run folder of every such study.
SEPARATORS = re.compile(r"[^\w.-]+", re.UNICODE)
COLLAPSED = "_"
# What a segment may not consist of ONLY. This covers "", ".", "..", "..." and a run of dashes or
# underscores in one test, without a list of special cases to keep up to date.
PUNCTUATION = "._-"


def safe_segment(text: str, fallback: str = "") -> str:
    """`text` as one path segment, safe to join onto a directory.

    Every separator becomes an underscore, so nothing that comes out of here can name a parent,
    a drive or a second folder. A value that leaves no letters or digits behind is refused with a
    `ValueError`, because there is then nothing to write and inventing a name would put the file
    somewhere nobody looks - unless the caller names a `fallback`, which is for text a human typed
    (the project name in the dialog) rather than text a service sent.
    """
    cleaned = SEPARATORS.sub(COLLAPSED, str(text).strip()).strip(COLLAPSED)
    if not cleaned.strip(PUNCTUATION):
        if fallback:
            return fallback
        raise ValueError(f"geen bruikbare bestandsnaam over van {text!r}")
    return cleaned
