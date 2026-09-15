"""De pijplijn: van een kernresultaat naar een PDF, een projectbestand en een GeoPackage.

De offline test draait de hele tweede helft (`finish`) zonder ook maar een service aan te raken:
elke WMS-laag is een memory-laag, het reliëf komt uit een vaste tuple en de legenda's staan uit.
Dat bewijst de volgorde en de producten. De live test onderaan (`-m live`) draait de echte studie
voor Gent en is de enige die bewijst dat het geheel in de praktijk staat; de bladen blijven in
`uitvoer/pipeline_live` staan om te bekijken, want een PDF beoordeel je door ernaar te kijken.
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from tests.qgis.conftest import write_png

LIVE_OUT = Path(__file__).resolve().parents[2] / "uitvoer" / "pipeline_live"
CPT_KEY = "k1"
FIGURE_REL = f"figuren/cpt_{CPT_KEY}.png"
MIN_LIVE_PAGES = 60


def _meta():
    from desktopstudie.core.report_content import ReportMeta

    return ReportMeta(project="Testproject", author="A. Tester", company="Testbureau",
                      project_number="T-001")


def _log(lines=None):
    from desktopstudie.core.logging_util import Log

    return Log("pipeline", lines.append if lines is not None else (lambda _m: None), scope="qgis")


def _pdf_pages(path):
    data = path.read_bytes()
    return data.count(b"/Type /Page") - data.count(b"/Type /Pages")


@pytest.fixture
def core_result(gent_zone, tmp_path):
    """Een klein StudyResult zoals de kern het achterlaat: een sondering met een figuur, een
    kaartfeit, een mislukte bron en de afkapping die alleen de orchestrator kent."""
    from desktopstudie.core.model import Cpt, MapFact, Provenance, Signalering, StudyResult

    write_png(tmp_path / FIGURE_REL, 400, 600)
    result = StudyResult(zone=gent_zone, created_at="2026-09-15T10:00:00", municipality="Gent")
    result.cpts = [Cpt(CPT_KEY, "GEO-01", 104300.0, 192500.0, 8.0, 20.0, "2020-01-01",
                       "continu elektrisch", "M1", "Uitvoerder", "Opdracht",
                       f"https://www.dov.vlaanderen.be/data/sondering/{CPT_KEY}", 12.0)]
    result.map_facts = [MapFact("bodemkaart", "Bodemkaart van Vlaanderen",
                                [{"Bodemtype": "Ldc", "Bodemserie": "Ldc", "Textuurklasse": "zandleem"}])]
    result.figures = {f"cpt_{CPT_KEY}": FIGURE_REL}
    result.provenance = [Provenance("DOV WFS", "https://dov/wfs", "2026-09-15T10:00:00", True),
                         Provenance("Watertoets", "https://vmm/wms", "2026-09-15T10:00:00", False, "HTTP 503")]
    result.signaleringen = [Signalering("wfs_afgekapt", "dov-pub:Sonderingen: 5 van 90 objecten opgehaald.",
                                        "DOV WFS", "Verhoog max_features.", severity="info")]
    return result


@pytest.fixture
def offline_shell(monkeypatch, gent_zone):
    """Geen enkele service: elke WMS-laag is een memory-laag en het reliëf is een vaste tuple van
    4,4 m verschil - genoeg om de reliëfregel te laten aanslaan."""
    from desktopstudie.qgis import dem, layers

    def fake_wms(entry):
        layer = layers.zone_layer(gent_zone)
        layer.setName(entry.title)
        return layer

    monkeypatch.setattr(layers, "wms_layer", fake_wms)
    monkeypatch.setattr(dem, "relief_of_zone",
                        lambda zone_layer, log=None, should_cancel=None: (5.0, 9.4, 7.1))
    return (5.0, 9.4, 7.1)


# --- offline ---------------------------------------------------------------------------------

def test_finish_delivers_the_report_the_project_and_the_geopackage(project, core_result, offline_shell,
                                                                   tmp_path):
    """Wat een studie oplevert: een PDF met elk hoofdstuk erin, de bladen als PNG, een GeoPackage
    en een zelfstandig project - allemaal in dezelfde uitvoermap."""
    from desktopstudie.qgis import pipeline

    steps = []
    out = pipeline.finish(project, core_result, _meta(), tmp_path, _log(),
                          progress=lambda f, m: steps.append((f, m)), legends=False)

    assert out.pdf == tmp_path / "rapport.pdf" and out.pdf.exists()
    assert len(out.report.chapters) == 8
    pages = _pdf_pages(out.pdf)
    assert pages >= len(out.report.chapters) + 1, f"{pages} pagina's voor 8 hoofdstukken"
    assert [path.name for path in out.page_pngs[:2]] == ["pagina.png", "pagina_2.png"]
    assert len(out.page_pngs) == pages
    assert out.project_file == tmp_path / "studie.qgz" and out.project_file.exists()
    assert out.geopackage == tmp_path / "data" / "studie.gpkg" and out.geopackage.exists()
    assert steps and steps[-1][0] == 1.0


def test_finish_measures_the_relief_and_runs_the_rules_again(project, core_result, offline_shell, tmp_path):
    """Het reliëf komt pas in de schil binnen, dus de signaleringen moeten daarna opnieuw: de
    reliëfregel kan pas dan aanslaan. De afkapping van de WFS overleeft die tweede pas, want geen
    enkele regel kan die uit het resultaat afleiden."""
    import json

    from desktopstudie.qgis import pipeline

    pipeline.finish(project, core_result, _meta(), tmp_path, _log(), legends=False)

    assert core_result.relief == offline_shell
    codes = [signal.code for signal in core_result.signaleringen]
    assert "relief" in codes, codes  # 5,0 tot 9,4 mTAW is meer dan 2 m verschil
    assert "wfs_afgekapt" in codes, codes
    assert "bron_niet_beschikbaar" in codes, codes
    data = json.loads((tmp_path / "data" / "studie.json").read_text(encoding="utf-8"))
    assert data["relief"] == [5.0, 9.4, 7.1]
    assert any(signal["code"] == "relief" for signal in data["signaleringen"])


def test_the_open_project_gets_the_study_groups_and_one_layout(project, core_result, offline_shell, tmp_path):
    """De lagen komen in het project dat de gebruiker openheeft, in hoofdstukgroepen, en de layout
    hoort erbij: die staat daarna in de layoutbeheerder, niet alleen in het geheugen."""
    from desktopstudie.qgis import layout, pipeline

    pipeline.finish(project, core_result, _meta(), tmp_path, _log(), legends=False)

    names = [group.name() for group in project.layerTreeRoot().findGroups()]
    assert names == list(pipeline.CHAPTER_GROUPS.values()) + ["4 Onderzoekszone en doorsnede",
                                                              "5 Grondonderzoek DOV"]
    assert project.layoutManager().layoutByName(layout.LAYOUT_NAME) is not None


def test_a_second_run_replaces_the_layout_instead_of_stacking_them(project, core_result, offline_shell,
                                                                   tmp_path):
    """Twee studies in dezelfde QGIS-sessie: de tweede hoort de layout van de eerste te vervangen.
    Anders staan er twee gelijknamige rapporten in de layoutbeheerder en kiest de gebruiker blind."""
    from desktopstudie.qgis import layout, pipeline

    pipeline.finish(project, core_result, _meta(), tmp_path / "een", _log(), legends=False)
    pipeline.finish(project, core_result, _meta(), tmp_path / "twee", _log(), legends=False)

    layouts = [item.name() for item in project.layoutManager().printLayouts()]
    assert layouts.count(layout.LAYOUT_NAME) == 1


def test_a_cancelled_run_stops_before_it_writes_a_report(project, core_result, offline_shell, tmp_path):
    """Afbreken hoort te stoppen, niet stilletjes door te draaien: geen half rapport in de map."""
    from desktopstudie.core.study import StudyCancelled
    from desktopstudie.qgis import pipeline

    with pytest.raises(StudyCancelled):
        pipeline.finish(project, core_result, _meta(), tmp_path, _log(), legends=False,
                        should_cancel=lambda: True)

    assert not (tmp_path / "rapport.pdf").exists()


def test_the_font_dir_is_secured_before_the_first_render(project, core_result, offline_shell, tmp_path,
                                                         monkeypatch):
    """Headless zonder QT_QPA_FONTDIR komt elke letter als zwart blokje uit de export, zonder één
    foutmelding. De pijplijn zet de map dus zelf en zegt dat in het log."""
    from desktopstudie.qgis import pipeline

    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.delenv("QT_QPA_FONTDIR", raising=False)
    lines = []

    pipeline.finish(project, core_result, _meta(), tmp_path, _log(lines), legends=False)

    import os

    assert os.environ.get("QT_QPA_FONTDIR")
    assert any("QT_QPA_FONTDIR" in line for line in lines), lines


# --- live ------------------------------------------------------------------------------------

@pytest.mark.live
def test_live_pipeline_for_gent(project, tmp_path):
    """De echte studie van begin tot eind: kern, reliëf, rapport, kaarten, export. De uitvoer
    blijft in uitvoer/pipeline_live staan - de bladen horen bekeken te worden voor "klaar"."""
    import shutil

    from desktopstudie.core import geometry, study
    from desktopstudie.core.model import StudyZone
    from desktopstudie.qgis import pipeline

    if LIVE_OUT.exists():
        shutil.rmtree(LIVE_OUT)
    LIVE_OUT.mkdir(parents=True)
    zone = StudyZone(ring=geometry.buffer_point(104326.0, 192506.0, 50.0), name="Gent test",
                     radius_m=500.0, address="Kortrijksesteenweg 100, 9000 Gent")
    lines = []
    started = time.monotonic()

    out = pipeline.run_pipeline(zone, study.Settings(radius_m=500.0), _meta(), LIVE_OUT, project,
                                _log(lines))

    elapsed = time.monotonic() - started
    pages = _pdf_pages(out.pdf)
    print(f"\nlive pijplijn Gent: {elapsed:.0f} s, {pages} pagina's, {len(out.page_pngs)} PNG's "
          f"-> {LIVE_OUT}")
    assert pages >= MIN_LIVE_PAGES, f"{pages} pagina's"
    assert len(out.page_pngs) == pages
    assert out.project_file.exists() and out.geopackage.exists()
    assert isinstance(out.result.relief, tuple) and len(out.result.relief) == 3
    assert out.result.cpts and out.result.boreholes
    warnings = [line for line in lines if "WARNING" in line]
    print("\n".join(warnings[:20]))
