from __future__ import annotations

import pytest

from desktopstudie.core.logging_util import Log


def test_log_formats_with_prefix_and_collects_lines():
    lines = []
    log = Log("dov_wfs", sink=lines.append, level="DEBUG")
    log.info("12 CPT's, 3 zonder XML")
    log.debug("row 7 skipped")
    assert lines == [
        "[core INFO dov_wfs] 12 CPT's, 3 zonder XML",
        "[core DEBUG dov_wfs] row 7 skipped",
    ]


def test_log_child_keeps_sink():
    lines = []
    log = Log("study", sink=lines.append).child("section")
    log.warning("bron niet bereikbaar")
    assert lines == ["[core WARNING section] bron niet bereikbaar"]


def test_default_level_info_drops_debug():
    lines = []
    log = Log("dov_wfs", sink=lines.append)
    log.debug("row 7 skipped")
    log.info("12 CPT's, 3 zonder XML")
    assert lines == ["[core INFO dov_wfs] 12 CPT's, 3 zonder XML"]


def test_child_inherits_level():
    lines = []
    log = Log("study", sink=lines.append, level="WARNING").child("section")
    log.info("wordt genegeerd")
    log.warning("bron niet bereikbaar")
    assert lines == ["[core WARNING section] bron niet bereikbaar"]


def test_unknown_level_is_rejected_at_construction():
    with pytest.raises(ValueError):
        Log("study", level="TRACE")
