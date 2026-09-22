"""Het bugjachtgereedschap kijkt zijn eigen runs na, dus wat het NIET ziet wordt nooit gemeld.

De nakijkregels horen daarom uit de data te komen en niet uit de Nederlandse zin van een
signalering: wie die zin herschrijft, legt anders stilzwijgend een regel plat en het script meldt
"in orde". In de QGIS-Python, want het script importeert `qgis.core`.
"""
from __future__ import annotations

from types import SimpleNamespace

MANY = ["zandsteen", "veen", "puin", "glauconiet", "turf", "steenkool", "asfalt"]


def _borehole(number, description):
    from desktopstudie.core.model import Borehole, LithologyLayer

    return Borehole(permkey=number, number=number, x=104326.0, y=192506.0, z_mtaw=10.0,
                    depth_m=5.0, date=None, method=None, purpose=None, contractor=None,
                    url="", distance_m=0.0,
                    lithology=[LithologyLayer(0.0, 5.0, description)])


def _outcome(boreholes, zone):
    from desktopstudie.core.model import StudyResult
    from desktopstudie.core.report_content import Report

    result = StudyResult(zone=zone, created_at="2026-09-22")
    result.boreholes = list(boreholes)
    return SimpleNamespace(result=result, failures=[], report=Report(title="t", meta={}, chapters=[]),
                           sheets=0, page_pngs=[])


def test_a_remark_line_drowning_in_terms_is_a_finding_however_the_sentence_reads(tmp_path, gent_zone):
    """"opmerkingsregels die in ruis verzuipen" - geteld op de TERMEN die de woordenlijst vlagt,
    niet op de zin die de signalering erover schrijft. Die zin mag herschreven worden."""
    from scripts import random_study

    boreholes = [_borehole("kb12d37w-B19", " ".join(f"{word} laag" for word in MANY))]

    found = random_study.inspect(1, "hier", tmp_path, _outcome(boreholes, gent_zone), None)

    assert [line for line in found.ours if "opmerkingsregel" in line], found.ours
    assert "kb12d37w-B19" in found.ours[0], found.ours


def test_a_short_remark_line_is_not_a_finding(tmp_path, gent_zone):
    from scripts import random_study

    boreholes = [_borehole("kb12d37w-B20", "bruin zand met grijze klei")]

    found = random_study.inspect(1, "hier", tmp_path, _outcome(boreholes, gent_zone), None)

    assert found.ok(), found.ours
