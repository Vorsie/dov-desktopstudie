from __future__ import annotations

from desktopstudie.core.logging_util import Log


def test_log_formats_with_prefix_and_collects_lines():
    lines = []
    log = Log("dov_wfs", sink=lines.append)
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
