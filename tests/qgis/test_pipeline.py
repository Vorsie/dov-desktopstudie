"""De pijplijn: van een kernresultaat naar een GeoPackage, een projectbestand en een PDF.

De offline tests draaien de hele tweede helft (`finish`) zonder ook maar een service aan te raken:
elke WMS-laag is een memory-laag, het reliëf komt uit een vaste tuple en de legenda's staan uit.
Eén volledige run draagt de meeste beweringen - een rapport renderen kost seconden, dus dat gebeurt
zo weinig mogelijk; de faalpaden krijgen hun eigen, kleine run zonder echte export. De live test
onderaan (`-m live`) draait de echte studie voor Gent en laat de bladen in `uitvoer/pipeline_live2`
staan om te bekijken, want een PDF beoordeel je door ernaar te kijken.
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from tests.qgis.conftest import write_png

LIVE_OUT = Path(__file__).resolve().parents[2] / "uitvoer" / "pipeline_live2"
CPT_KEY = "k1"
FIGURE_REL = f"figuren/cpt_{CPT_KEY}.png"
MIN_LIVE_PAGES = 60
RELIEF = (5.0, 9.4, 7.1)  # 4,4 m verschil: genoeg om de reliëfregel te laten aanslaan


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
    kaartfeit, een geslaagde bron en de afkapping die alleen de orchestrator kent."""
    from desktopstudie.core.model import Cpt, MapFact, Provenance, Signalering, StudyResult

    write_png(tmp_path / FIGURE_REL, 400, 600)
    result = StudyResult(zone=gent_zone, created_at="2026-09-15T10:00:00", municipality="Gent")
    result.cpts = [Cpt(CPT_KEY, "GEO-01", 104300.0, 192500.0, 8.0, 20.0, "2020-01-01",
                       "continu elektrisch", "M1", "Uitvoerder", "Opdracht",
                       f"https://www.dov.vlaanderen.be/data/sondering/{CPT_KEY}", 12.0)]
    result.map_facts = [MapFact("bodemkaart", "Bodemkaart van Vlaanderen",
                                [{"Bodemtype": "Ldc", "Bodemserie": "Ldc", "Textuurklasse": "zandleem"}])]
    result.figures = {f"cpt_{CPT_KEY}": FIGURE_REL}
    result.provenance = [Provenance("DOV WFS", "https://dov/wfs", "2026-09-15T10:00:00", True)]
    result.signaleringen = [Signalering("wfs_afgekapt", "dov-pub:Sonderingen: 5 van 90 objecten opgehaald.",
                                        "DOV WFS", "Verhoog max_features.", severity="info")]
    return result


@pytest.fixture
def offline_shell(monkeypatch, gent_zone):
    """Geen enkele service, en een catalogus van drie kaarten.

    Elke WMS-laag is een memory-laag en het reliëf is een vaste tuple. De catalogus wordt
    teruggebracht tot een kaart per hoofdstuk omdat deze tests over de volgorde en de producten van
    de pijplijn gaan, niet over de omvang van de catalogus: met alle dertig kaarten kost één
    rapport vijf minuten renderen en wordt de suite niet meer gedraaid. De live test dekt de echte
    catalogus.
    """
    from desktopstudie.core import catalogue
    from desktopstudie.qgis import dem, layers

    def fake_wms(entry):
        layer = layers.zone_layer(gent_zone)
        layer.setName(entry.title)
        return layer

    # grb blijft: hoofdstuk 5 en 6 tekenen hun overzichtskaart daarop. quartair blijft omdat het
    # de enige kaart is die haar legenda als tekening per profieltype ophaalt.
    monkeypatch.setattr(catalogue, "CATALOGUE",
                        [catalogue.by_id(map_id)
                         for map_id in ("grb", "ferraris", "bodemkaart", "quartair")])
    monkeypatch.setattr(layers, "wms_layer", fake_wms)
    monkeypatch.setattr(dem, "relief_of_zone",
                        lambda zone_layer, log=None, should_cancel=None: RELIEF)
    return RELIEF


@pytest.fixture
def no_pdf(monkeypatch):
    """Voor tests waar de export zelf niet de vraag is: schrijven kost seconden per rapport."""
    from desktopstudie.qgis import export

    monkeypatch.setattr(export, "export_pdf", lambda lay, path, dpi=150: Path(path))


# --- offline: één volledige run draagt de meeste beweringen ------------------------------------

@pytest.mark.slow
def test_finish_delivers_the_study_and_leaves_the_project_usable(project, core_result, offline_shell,
                                                                 tmp_path):
    """Eén run, en dan kijken naar alles wat ze hoort achter te laten: de drie producten, het
    reliëf met zijn bronvermelding, de opnieuw gedraaide regels, de groepen en de layout in het
    project, en een voortgangsbalk die tot het einde loopt."""
    import json

    from desktopstudie.qgis import layout, pipeline

    steps = []
    out = pipeline.finish(project, core_result, _meta(), tmp_path, _log(),
                          progress=lambda f, m: steps.append((f, m)), legends=False, pngs=True)

    # de producten
    assert out.pdf == tmp_path / "rapport.pdf" and out.pdf.exists()
    assert out.failures == []
    assert len(out.report.chapters) == 8
    pages = _pdf_pages(out.pdf)
    assert pages >= len(out.report.chapters) + 1, f"{pages} pagina's voor 8 hoofdstukken"
    assert [path.name for path in out.page_pngs[:2]] == ["pagina.png", "pagina_2.png"]
    assert len(out.page_pngs) == pages
    assert out.project_file == tmp_path / "studie.qgz" and out.project_file.exists()
    assert out.geopackage == tmp_path / "data" / "studie.gpkg" and out.geopackage.exists()
    assert steps and steps[-1][0] == 1.0

    # het reliëf en de tweede pas van de regels
    assert core_result.relief == offline_shell
    codes = [signal.code for signal in core_result.signaleringen]
    assert "relief" in codes, codes
    assert "wfs_afgekapt" in codes, codes
    data = json.loads((tmp_path / "data" / "studie.json").read_text(encoding="utf-8"))
    assert data["relief"] == list(RELIEF)
    assert any(signal["code"] == "relief" for signal in data["signaleringen"])
    assert any(p["source"] == "DHMV II relief" and p["ok"] for p in data["provenance"])

    # het project waarin de gebruiker verder werkt
    names = [group.name() for group in project.layerTreeRoot().findGroups()]
    assert names == list(pipeline.CHAPTER_GROUPS.values()) + ["4 Onderzoekszone en doorsnede",
                                                             "5 Grondonderzoek DOV"]
    assert project.layoutManager().layoutByName(layout.LAYOUT_NAME) is not None


def test_a_second_run_replaces_the_layout_instead_of_stacking_them(project, core_result, offline_shell,
                                                                   tmp_path, no_pdf):
    """Twee studies in dezelfde QGIS-sessie: de tweede hoort de layout van de eerste te vervangen.
    Anders staan er twee gelijknamige rapporten in de layoutbeheerder en kiest de gebruiker blind.
    Hetzelfde geldt voor de kaartkopieën die de layout tekent: die staan buiten de lagenboom, dus
    niemand kan ze met de hand opruimen als ze zich opstapelen."""
    from desktopstudie.qgis import layout, pipeline

    pipeline.finish(project, core_result, _meta(), tmp_path / "een", _log(), legends=False)
    pipeline.finish(project, core_result, _meta(), tmp_path / "twee", _log(), legends=False)

    layouts = [item.name() for item in project.layoutManager().printLayouts()]
    assert layouts.count(layout.LAYOUT_NAME) == 1
    report_copies = [layer for layer in project.mapLayers().values()
                     if layer.customProperty(pipeline.REPORT_OVERLAY_FLAG)]
    assert len(report_copies) == 6, [layer.name() for layer in report_copies]


def test_the_report_maps_label_only_the_investigations_with_a_figure(project, core_result, offline_shell,
                                                                     tmp_path, no_pdf):
    """Tweehonderd nummers over elkaar maken de overzichtskaart onleesbaar; alleen de proeven met
    een figuur krijgen een label op het blad. In QGIS blijft de laag met alle nummers staan."""
    from desktopstudie.qgis import layers, pipeline

    pipeline.finish(project, core_result, _meta(), tmp_path, _log(), legends=False)

    sonderingen = [layer for layer in project.mapLayers().values() if layer.name() == "Sonderingen"]
    assert len(sonderingen) == 2, "één laag voor de gebruiker, één kopie voor het rapport"
    assert sorted(layer.labeling().settings().fieldName for layer in sonderingen) == \
           sorted([layers.FIGURED_LABEL, "nummer"])
    figured = [layer for layer in sonderingen if layer.labeling().settings().isExpression][0]
    assert [f["met_figuur"] for f in figured.getFeatures()] == [1], "de sondering heeft een figuur"


def test_the_zone_layer_is_built_once_and_serves_both_the_relief_and_the_maps(
        project, core_result, offline_shell, tmp_path, monkeypatch, no_pdf):
    """Eén zonelaag per run. `relief_of_zone` bemonstert toch al een kloon - het schrijft zijn drie
    kolommen niet op de laag van de oproeper - dus een tweede zonelaag bouwen levert niets op en
    zet twee objecten in het geheugen waar de lezer er één ziet."""
    from desktopstudie.qgis import dem, layers, pipeline

    built = []
    real = layers.zone_layer

    def counted(zone):
        built.append(real(zone))
        return built[-1]

    sampled = []

    def relief(zone_layer, log=None, should_cancel=None):
        sampled.append(zone_layer)
        return RELIEF

    monkeypatch.setattr(layers, "zone_layer", counted)
    monkeypatch.setattr(dem, "relief_of_zone", relief)

    pipeline.finish(project, core_result, _meta(), tmp_path, _log(), legends=False)

    # De nepkaartlagen van `offline_shell` zijn ook zonelagen, alleen hernoemd naar hun kaart;
    # alleen wat na de run nog "Onderzoekszone" heet, is de zonelaag van de studie.
    zones = [layer for layer in built if layer.name() == layers.ZONE_NAME]
    assert len(zones) == 1, "de zonelaag hoort één keer gebouwd te worden"
    assert sampled == zones, "het reliëf hoort op diezelfde laag te worden gemeten"


QUARTAIR_LEGEND = ("https://datasets.omgeving.vlaanderen.be/be.vlaanderen.omgeving.distribution.geo."
                   "e58c3358-e149-42b6-9229-c3a9ac88c3d4.DOV_Quartair_50000_{code}_png")


def test_the_quartair_drawings_are_fetched_by_the_shell_and_land_in_the_report(
        project, core_result, offline_shell, tmp_path, no_pdf):
    """De kern kan niets ophalen, dus de schil haalt de tekening van elk profieltype op en geeft ze
    aan `build_report` door; daar wordt ze een figuurpagina achter de legenda van de zone. Een
    tekening die niet binnenkwam, staat als mislukte bron in de provenance - niet stil weg."""
    from desktopstudie.core.model import MapFact
    from desktopstudie.core.report_content import FigurePage, LegendPage
    from desktopstudie.core.services.http import HttpClient, HttpError
    from desktopstudie.qgis import pipeline

    blob = write_png(tmp_path / "bron.png", 200, 300).read_bytes()
    core_result.map_facts.append(MapFact("quartair", "Quartairgeologische kaart", [
        {"profieltype": "22026", "legende": QUARTAIR_LEGEND.format(code="22026")},
        {"profieltype": "22098", "legende": QUARTAIR_LEGEND.format(code="22098")}]))

    class _Client(HttpClient):
        def get(self, url, params=None, timeout=None, retries=None, cache_mode=None):
            if url.endswith("22098_png"):
                raise HttpError(url, 500, "dienst plat")
            return blob

    out = pipeline.finish(project, core_result, _meta(), tmp_path, _log(), legends=False,
                          client=_Client(cache_dir=None))

    # De kopstrook staat op de legendapagina zelf; alleen de eenhedentabel van het kaartblad
    # krijgt een eigen blad.
    pages = out.report.chapters[2].pages
    legend = next(page for page in pages if isinstance(page, LegendPage))
    assert [(entry.code, entry.image_path) for entry in legend.entries] == [
        ("22026", "legendas/quartair_22026_kop.png"), ("22098", "")]
    figures = [page for page in pages if isinstance(page, FigurePage)]
    assert [(page.title, page.image_path) for page in figures] == [
        ("Eenheden op kaartblad 22", "legendas/quartair_kaartblad_22.png")]
    assert (tmp_path / "legendas" / "quartair_22026_kop.png").exists()
    assert (tmp_path / "legendas" / "quartair_kaartblad_22.png").exists()
    provenance = {p.source: p.ok for p in core_result.provenance}
    assert provenance["Legenda profieltype 22026"] is True
    assert provenance["Legenda profieltype 22098"] is False


# --- offline: wat er gebeurt als iets faalt ----------------------------------------------------

def test_a_relief_that_cannot_be_measured_is_reported_as_a_failed_source(project, core_result,
                                                                        offline_shell, tmp_path,
                                                                        monkeypatch, no_pdf):
    """Geen reliëf is geen stilte: de DHMV komt als mislukte bron in de provenance en daarmee als
    signalering in het rapport - anders leest een vlakke zone hetzelfde als een onbereikbare
    dienst."""
    from desktopstudie.qgis import dem, pipeline

    monkeypatch.setattr(dem, "relief_of_zone", lambda zone_layer, log=None, should_cancel=None: None)

    pipeline.finish(project, core_result, _meta(), tmp_path, _log(), legends=False)

    failed = [p for p in core_result.provenance if not p.ok]
    assert [p.source for p in failed] == ["DHMV II relief"]
    assert any(s.code == "bron_niet_beschikbaar" for s in core_result.signaleringen)


def test_a_wms_layer_that_does_not_load_is_named_in_the_sources(project, core_result, offline_shell,
                                                                tmp_path, monkeypatch, no_pdf):
    """Een kaartlaag die de dienst niet levert, kost haar eigen kaartpagina. Dat hoort in de
    bronnenlijst te staan, niet alleen in een logregel die niemand bewaart."""
    from qgis.core import QgsRasterLayer

    from desktopstudie.core import catalogue
    from desktopstudie.qgis import layers, pipeline

    real = layers.wms_layer

    def half_broken(entry):
        if entry.id == "ferraris":
            return QgsRasterLayer("", entry.title, "wms")  # ongeldig, zoals een dienst die plat ligt
        return real(entry)

    monkeypatch.setattr(layers, "wms_layer", half_broken)

    pipeline.finish(project, core_result, _meta(), tmp_path, _log(), legends=False)

    failed = {p.source: p for p in core_result.provenance if not p.ok}
    title = catalogue.by_id("ferraris").title
    assert f"Kaartlaag {title}" in failed, sorted(failed)
    assert "ongeldig" in failed[f"Kaartlaag {title}"].message.lower()


def test_a_failed_pdf_still_leaves_the_project_and_the_geopackage(project, core_result, offline_shell,
                                                                  tmp_path, monkeypatch):
    """De PDF is het laatste product, niet het enige. Loopt de export stuk, dan houdt de gebruiker
    het GeoPackage en het projectbestand - en de melding zegt wat er mis ging."""
    from desktopstudie.qgis import export, pipeline

    def boom(lay, path, dpi=150):
        raise RuntimeError("PDF-export mislukt (FileError)")

    monkeypatch.setattr(export, "export_pdf", boom)

    out = pipeline.finish(project, core_result, _meta(), tmp_path, _log(), legends=False)

    assert out.pdf is None
    assert out.failures and "FileError" in out.failures[0]
    assert out.geopackage.exists() and out.project_file.exists()


def test_a_cancelled_run_stops_before_it_writes_a_report(project, core_result, offline_shell, tmp_path):
    """Afbreken hoort te stoppen, niet stilletjes door te draaien: geen half rapport in de map."""
    from desktopstudie.core.study import StudyCancelled
    from desktopstudie.qgis import pipeline

    with pytest.raises(StudyCancelled):
        pipeline.finish(project, core_result, _meta(), tmp_path, _log(), legends=False,
                        should_cancel=lambda: True)

    assert not (tmp_path / "rapport.pdf").exists()


def test_the_font_dir_is_secured_before_the_first_render(project, core_result, offline_shell, tmp_path,
                                                         monkeypatch, no_pdf):
    """Headless zonder QT_QPA_FONTDIR komt elke letter als zwart blokje uit de export, zonder één
    foutmelding. De pijplijn zet de map dus zelf en zegt dat in het log."""
    import os

    from desktopstudie.qgis import pipeline

    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.delenv("QT_QPA_FONTDIR", raising=False)
    lines = []

    pipeline.finish(project, core_result, _meta(), tmp_path, _log(lines), legends=False)

    assert os.environ.get("QT_QPA_FONTDIR")
    assert any("QT_QPA_FONTDIR" in line for line in lines), lines


# --- live --------------------------------------------------------------------------------------

@pytest.mark.live
def test_live_pipeline_for_gent(project, tmp_path):
    """De echte studie van begin tot eind: kern, reliëf, rapport, kaarten, export. De uitvoer
    blijft in uitvoer/pipeline_live2 staan - de bladen horen bekeken te worden voor "klaar"."""
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
    marks = {}
    started = time.monotonic()

    out = pipeline.run_pipeline(zone, study.Settings(radius_m=500.0), _meta(), LIVE_OUT, project,
                                _log(lines), progress=lambda f, m: marks.setdefault(m, time.monotonic()),
                                pngs=True)

    elapsed = time.monotonic() - started
    core_done = marks.get("Relief uit DHMV", started) - started
    pages = _pdf_pages(out.pdf)
    print(f"\nlive pijplijn Gent: {elapsed:.0f} s totaal ({core_done:.0f} s kern, "
          f"{elapsed - core_done:.0f} s schil), {pages} pagina's, {len(out.page_pngs)} PNG's "
          f"-> {LIVE_OUT}")
    assert pages >= MIN_LIVE_PAGES, f"{pages} pagina's"
    assert len(out.page_pngs) == pages
    assert out.failures == [], out.failures
    assert out.project_file.exists() and out.geopackage.exists()
    assert isinstance(out.result.relief, tuple) and len(out.result.relief) == 3
    assert out.result.cpts and out.result.boreholes
    print("\n".join(line for line in lines if "WARNING" in line)[:2000])


def test_a_layout_that_cannot_be_installed_stops_the_run(project, core_result, offline_shell, tmp_path,
                                                         monkeypatch, no_pdf):
    """`addLayout` neemt het eigendom over en VERNIETIGT de layout als ze weigert. Doorgaan met dat
    object is werken in vrijgegeven geheugen; dan hoort de run te stoppen met een leesbare fout."""
    from desktopstudie.qgis import pipeline

    monkeypatch.setattr(type(project.layoutManager()), "addLayout", lambda self, lay: False)

    with pytest.raises(RuntimeError, match="Layout"):
        pipeline.finish(project, core_result, _meta(), tmp_path, _log(), legends=False)


def test_a_geopackage_that_cannot_be_written_still_leaves_the_json(project, core_result, offline_shell,
                                                                   tmp_path, monkeypatch, no_pdf):
    """Het gewone geval bij herhaald draaien: de vorige studie houdt het GeoPackage vast. Dan hoort
    de gebruiker nog altijd zijn data te krijgen - studie.json staat er, de fout staat in
    `failures`, en het rapport gaat gewoon door."""
    from desktopstudie.qgis import layers, pipeline

    def locked(*args, **kwargs):
        raise RuntimeError("GeoPackage schrijven mislukt voor Onderzoekszone: database is locked")

    monkeypatch.setattr(layers, "write_geopackage", locked)

    out = pipeline.finish(project, core_result, _meta(), tmp_path, _log(), legends=False)

    assert (tmp_path / "data" / "studie.json").exists(), "de json is het goedkoopste product"
    assert out.geopackage is None and out.project_file is None
    assert out.failures and "locked" in out.failures[0]
    assert out.pdf is not None, "een vastgehouden GeoPackage kost het rapport niet"


def test_the_json_is_written_before_the_heavy_products(project, core_result, offline_shell, tmp_path,
                                                        monkeypatch, no_pdf):
    """Volgorde van goedkoop naar duur: wie halverwege afbreekt, houdt in elk geval de data."""
    from desktopstudie.qgis import layers, pipeline

    order = []
    real_gpkg = layers.write_geopackage
    monkeypatch.setattr(layers, "write_geopackage",
                        lambda *a, **k: (order.append("gpkg"), real_gpkg(*a, **k))[1])
    real_write = type(core_result).write_json
    monkeypatch.setattr(type(core_result), "write_json",
                        lambda self, path: (order.append("json"), real_write(self, path))[1])

    pipeline.finish(project, core_result, _meta(), tmp_path, _log(), legends=False)

    assert order == ["json", "gpkg"]


def test_a_cancelled_export_is_not_swallowed_as_a_failure(project, core_result, offline_shell, tmp_path,
                                                          monkeypatch):
    """Afbreken is geen mislukte export: het hoort door te komen als StudyCancelled, niet als een
    regel in `failures` met een run die daarna "klaar" meldt."""
    from desktopstudie.core.study import StudyCancelled
    from desktopstudie.qgis import export, pipeline

    def cancelled(lay, path, dpi=150):
        raise StudyCancelled("afgebroken door de gebruiker")

    monkeypatch.setattr(export, "export_pdf", cancelled)

    with pytest.raises(StudyCancelled):
        pipeline.finish(project, core_result, _meta(), tmp_path, _log(), legends=False)


def test_a_map_that_draws_nothing_here_is_noted_but_not_failed(project, core_result, offline_shell,
                                                               tmp_path, monkeypatch, no_pdf):
    """De Popp-kaart is in Gent wit: het mozaiek heeft daar geen blad. De dienst antwoordde wel, dus
    de bron blijft "ok" - met de reden erbij, zodat het witte blad verklaard is."""
    from desktopstudie.qgis import layout, pipeline

    def no_popp(entries, zone_ring, client, log=None, should_cancel=None):
        return {"ferraris"}

    monkeypatch.setattr(layout, "prepare_coverage", no_popp)

    out = pipeline.finish(project, core_result, _meta(), tmp_path, _log(), legends=False)

    kaartlaag = next(p for p in out.result.provenance if p.source.startswith("Kaartlaag Ferraris"))
    assert kaartlaag.ok is True
    assert kaartlaag.message == pipeline.NO_COVERAGE_MESSAGE
    others = [p for p in out.result.provenance if p.source.startswith("Kaartlaag") and p is not kaartlaag]
    assert all(p.message == "" for p in others), [p.source for p in others]
