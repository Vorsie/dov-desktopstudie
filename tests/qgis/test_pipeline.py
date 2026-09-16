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
    from desktopstudie.qgis import layout as layout_mod

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

    def fake_map_images(requests, out_dir, client, log=None, should_cancel=None):
        """Elk kaartbeeld als een klein plaatje op schijf, zonder een dienst aan te raken."""
        from desktopstudie.qgis import layout

        images = {}
        for request in requests:
            path = Path(out_dir) / "data" / "kaarten" / f"{request.key.replace(':', '_')}.png"
            write_png(path, 60, 60)
            layout._write_world_file(path.with_suffix(".pgw"), request)
            images[request.key] = path
        return images, set()

    monkeypatch.setattr(layout_mod, "prepare_map_images", fake_map_images)
    return RELIEF


@pytest.fixture
def no_pdf(monkeypatch):
    """Voor tests waar de export zelf niet de vraag is: schrijven kost seconden per rapport."""
    from desktopstudie.qgis import export

    monkeypatch.setattr(export, "export_pdf", lambda lay, path, **kwargs: Path(path))


# --- offline: één volledige run draagt de meeste beweringen ------------------------------------

@pytest.mark.slow
def test_finish_delivers_the_study_and_leaves_the_project_usable(project, core_result, offline_shell,
                                                                 tmp_path):
    """Eén run, en dan kijken naar alles wat ze hoort achter te laten: de drie producten, het
    reliëf met zijn bronvermelding, de opnieuw gedraaide regels, de groepen en de layout in het
    project, en een voortgangsbalk die tot het einde loopt."""
    import json
    import re

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
    # De langste fase zegt hoe ver ze is: na elke run van de exporter het aantal bladen.
    assert any(re.fullmatch(r"PDF-export: \d+/\d+ bladen", message) for _f, message in steps), steps
    assert "PDF-export" in [name for name, _seconds in out.timings]

    # het reliëf en de tweede pas van de regels
    assert core_result.relief == offline_shell
    codes = [signal.code for signal in core_result.signaleringen]
    assert "relief" in codes, codes
    assert "wfs_afgekapt" in codes, codes
    data = json.loads((tmp_path / "data" / "studie.json").read_text(encoding="utf-8"))
    assert data["relief"] == list(RELIEF)
    assert any(signal["code"] == "relief" for signal in data["signaleringen"])
    assert any(p["source"] == "DHMV II relief" and p["ok"] for p in data["provenance"])

    # het project waarin de gebruiker verder werkt: één groep per studie, de hoofdstukken erin
    top = [group.name() for group in project.layerTreeRoot().findGroups()]
    assert top == [pipeline.study_group_name("Testproject")]
    study = project.layerTreeRoot().findGroup(top[0])
    assert [group.name() for group in study.findGroups()] == \
        list(pipeline.CHAPTER_GROUPS.values()) + ["4 Onderzoekszone en doorsnede", "5 Grondonderzoek DOV"]
    assert project.layoutManager().layoutByName(layout.layout_name("Testproject")) is not None


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
    assert layouts == [layout.layout_name("Testproject")]
    # De zes gestileerde kopieën van de tweede run plus haar kaartbeelden - en niets van de eerste.
    report_copies = [layer for layer in project.mapLayers().values()
                     if layer.customProperty(pipeline.REPORT_OVERLAY_FLAG)]
    names = sorted(layer.name() for layer in report_copies)
    assert sum(1 for name in names if not name.endswith("(kaartbeeld)")) == 6, names
    snapshots = [name for name in names if name.endswith("(kaartbeeld)")]
    assert snapshots and len(snapshots) == len(set(id(layer) for layer in report_copies
                                                   if layer.name().endswith("(kaartbeeld)")))


def test_the_network_half_runs_without_a_project_and_finish_takes_what_it_fetched(
        project, core_result, offline_shell, tmp_path, monkeypatch, no_pdf):
    """Alles wat alleen HTTP is - legenda's, profieltypetekeningen, kaartbeelden - hoort in de
    werkthread van de plugin te kunnen draaien, dus zonder project en zonder een enkele laag.
    `prepare` levert dat op; `finish` neemt het over en haalt niets een tweede keer op. De fasetabel
    van het geheel noemt beide helften, en elke kaartpagina vindt het beeld dat voor haar gepland
    is (dezelfde dozen aan beide kanten)."""
    from qgis.core import QgsLayoutItemLabel

    from desktopstudie.qgis import layout, pipeline

    fetched = []
    stand_in = layout.prepare_map_images  # the offline stand-in; counted, not replaced

    def counted(requests, out_dir, client, log=None, should_cancel=None):
        fetched.append(len(requests))
        return stand_in(requests, out_dir, client, log, should_cancel)

    monkeypatch.setattr(layout, "prepare_map_images", counted)
    steps = []

    prepared = pipeline.prepare(core_result, _meta(), tmp_path, _log(),
                                progress=lambda f, m: steps.append(m), legends=False)

    assert prepared.map_images and fetched == [len(prepared.requests)]
    assert [name for name, _seconds in prepared.timings] == ["Kaartbeelden"] == steps
    assert any(p.source.startswith(pipeline.MAP_IMAGE_SOURCE) and p.ok for p in core_result.provenance)
    assert not project.mapLayers(), "de netwerkhelft raakt het project niet aan"

    out = pipeline.finish(project, core_result, _meta(), tmp_path, _log(), legends=False,
                          prepared=prepared)

    assert fetched == [len(prepared.requests)], "finish hoort niets opnieuw op te halen"
    names = [name for name, _seconds in out.timings]
    assert names[0] == "Kaartbeelden" and "Relief uit DHMV" in names and names[-1] == "PDF-export"
    assert out.pdf is not None and out.failures == []
    lay = project.layoutManager().layoutByName(layout.layout_name("Testproject"))
    texts = [item.text() for item in lay.items() if isinstance(item, QgsLayoutItemLabel)]
    assert not any(layout.MISSING_MAP_NOTE in text for text in texts)
    assert any(layer.name().endswith("(kaartbeeld)") for layer in project.mapLayers().values())


def test_two_studies_live_side_by_side_and_only_a_same_named_one_replaces(project, core_result, offline_shell,
                                                                        tmp_path, no_pdf):
    """Beslissing: dezelfde studienaam vervangt. Gent en Antwerpen in één project blijven dus allebei
    staan - elk hun eigen groep, layout en rapportkopieën - en Gent nog eens vervangt alleen Gent."""
    import collections

    from desktopstudie.core.report_content import ReportMeta
    from desktopstudie.qgis import layers, layout, pipeline

    gent = _meta()
    antwerpen = ReportMeta(project="Antwerpen", author="A. Tester", company="Testbureau")

    pipeline.finish(project, core_result, gent, tmp_path / "a", _log(), legends=False)
    pipeline.finish(project, core_result, antwerpen, tmp_path / "b", _log(), legends=False)
    pipeline.finish(project, core_result, gent, tmp_path / "c", _log(), legends=False)

    root = project.layerTreeRoot()
    assert sorted(group.name() for group in root.findGroups()) == sorted(
        [pipeline.study_group_name("Testproject"), pipeline.study_group_name("Antwerpen")])
    assert sorted(item.name() for item in project.layoutManager().printLayouts()) == sorted(
        [layout.layout_name("Testproject"), layout.layout_name("Antwerpen")])
    for name in ("Testproject", "Antwerpen"):
        study = root.findGroup(pipeline.study_group_name(name))
        assert [group.name() for group in study.findGroups()] == \
            list(pipeline.CHAPTER_GROUPS.values()) + [layers.ZONE_GROUP, layers.INVESTIGATION_GROUP]
    owners = collections.Counter(layer.customProperty(pipeline.REPORT_OVERLAY_FLAG)
                                 for layer in project.mapLayers().values()
                                 if layer.customProperty(pipeline.REPORT_OVERLAY_FLAG))
    assert set(owners) == {"Testproject", "Antwerpen"} and owners["Testproject"] == owners["Antwerpen"]


def test_a_cancel_during_the_layers_phase_stops_before_the_next_layer(project, core_result, offline_shell,
                                                                     tmp_path, monkeypatch, no_pdf):
    """Annuleren wordt in elke fase binnen seconden gehoord - ook in de lagenfase, waar elke
    WMS-laag een netwerkronde is: na de laag die bezig was stopt de run, niet na alle."""
    from desktopstudie.core.study import StudyCancelled
    from desktopstudie.qgis import layers, pipeline

    built = []
    stand_in = layers.wms_layer

    def counted(entry):
        built.append(entry.id)
        return stand_in(entry)

    monkeypatch.setattr(layers, "wms_layer", counted)

    with pytest.raises(StudyCancelled):
        pipeline.finish(project, core_result, _meta(), tmp_path, _log(), legends=False,
                        should_cancel=lambda: len(built) >= 1)

    assert len(built) == 1, built


def test_the_study_group_opens_with_only_the_base_map_checked_and_the_chapters_collapsed(
        project, core_result, offline_shell, tmp_path, no_pdf):
    """Vijftien WMS-lagen tegelijk aan zetten het canvas aan het laden; alleen de GRB-basiskaart
    staat aan, de andere kaarten staan klaar maar uit, en de hoofdstukgroepen zijn ingeklapt."""
    from desktopstudie.core import catalogue
    from desktopstudie.qgis import pipeline

    pipeline.finish(project, core_result, _meta(), tmp_path, _log(), legends=False)

    study = project.layerTreeRoot().findGroup(pipeline.study_group_name("Testproject"))
    chapters = [study.findGroup(title) for title in pipeline.CHAPTER_GROUPS.values()]
    assert chapters and not any(group.isExpanded() for group in chapters)
    checked = [node.layer().name() for group in chapters for node in group.findLayers()
               if node.itemVisibilityChecked()]
    assert checked == [catalogue.by_id(pipeline.BASE_MAP_ID).title]


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


def test_the_quartair_drawings_are_fetched_by_the_shell_and_land_in_the_report(
        project, core_result, offline_shell, tmp_path, no_pdf):
    """De kern kan niets ophalen, dus de schil haalt de tekening van elk profieltype op en geeft ze
    aan `build_report` door; daar wordt ze een figuurpagina achter de legenda van de zone. Een
    tekening die niet binnenkwam, staat als mislukte bron in de provenance - niet stil weg."""
    from desktopstudie.core.report_content import FigurePage, LegendPage
    from desktopstudie.core.services.http import HttpClient, HttpError
    from desktopstudie.qgis import pipeline
    from tests import quartair

    blob = write_png(tmp_path / "bron.png", 200, 300).read_bytes()
    core_result.map_facts.append(quartair.map_fact(["22026", "22098"]))

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


def test_an_unchosen_map_gets_no_layer_no_legend_and_no_map_image(
        project, core_result, offline_shell, tmp_path, monkeypatch, no_pdf):
    """Een kaart die niet gekozen is, krijgt geen laag en geen legenda en geen kaartbeeld.

    De kaartenchecklist belooft dat letterlijk (README). Zonder dit kost een uitgevinkte kaart nog
    altijd een laag, een GetLegendGraphic en een GetMap, en drukt haar blad "Bron niet
    beschikbaar" af - dezelfde zin als een dienst die plat ligt.
    """
    from desktopstudie.core import catalogue
    from desktopstudie.core.report_content import MapPage
    from desktopstudie.qgis import layers, pipeline
    from desktopstudie.qgis import layout as layout_mod

    core_result.map_ids = ["grb", "bodemkaart", "quartair"]  # ferraris is uitgevinkt
    asked_legends = []

    def fake_legends(entries, out_dir, client, log=None, should_cancel=None):
        asked_legends.extend(entry.id for entry in entries)
        return {entry.id: write_png(Path(out_dir) / "legendas" / f"{entry.id}.png")
                for entry in entries}, []

    monkeypatch.setattr(layout_mod, "prepare_legends", fake_legends)
    built = []
    stand_in = layers.wms_layer

    def counted(entry):
        built.append(entry.id)
        return stand_in(entry)

    monkeypatch.setattr(layers, "wms_layer", counted)

    prepared = pipeline.prepare(core_result, _meta(), tmp_path, _log(), legends=True)
    out = pipeline.finish(project, core_result, _meta(), tmp_path, _log(), legends=False,
                          prepared=prepared)

    assert "bodemkaart" in asked_legends and "ferraris" not in asked_legends, asked_legends
    assert "grb" in built and "ferraris" not in built, built
    assert not any(request.map_id == "ferraris" for request in prepared.requests)
    ferraris = catalogue.by_id("ferraris").title
    assert not any(ferraris in p.source for p in core_result.provenance),         [p.source for p in core_result.provenance]
    assert not any(isinstance(page, MapPage) and page.map_id == "ferraris"
                   for chapter in out.report.chapters for page in chapter.pages)


def test_a_map_with_one_failed_image_is_a_failed_source(qgs_app, core_result, gent_zone, tmp_path,
                                                        monkeypatch):
    """Een kaart waarvan een beeld mislukt, staat als mislukte bron in het rapport.

    De GRB-basiskaart wordt op meer dan een kader opgehaald. Kwam er een niet binnen, dan drukt
    dat blad "Kaartbeeld van deze bron niet opgehaald" af; een bronnenregel die "ok" zegt omdat
    het volgende kader wel lukte, spreekt dat blad tegen.
    """
    from desktopstudie.core.report_content import Chapter, MapPage, Report
    from desktopstudie.qgis import layout as layout_mod
    from desktopstudie.qgis import pipeline

    pages = [MapPage("grb", "Ligging", scale=2500),
             MapPage("grb", "Overzicht", scale=5000, extent_factor=1.0)]
    report = Report(title="t", meta={}, chapters=[Chapter(1, "Test", pages)])
    requests = layout_mod.plan_map_images(report, gent_zone.ring, {})
    assert len(requests) == 2, [request.key for request in requests]

    def only_the_second(reqs, out_dir, client, log=None, should_cancel=None):
        write_png(Path(out_dir) / "kaarten" / "tweede.png")
        return {reqs[1].key: Path(out_dir) / "kaarten" / "tweede.png"}, set()

    monkeypatch.setattr(layout_mod, "prepare_map_images", only_the_second)

    pipeline._fetch_map_images(core_result, requests, tmp_path, None, _log(), None)

    images = [p for p in core_result.provenance if p.source.startswith(pipeline.MAP_IMAGE_SOURCE)]
    assert images and not any(p.ok for p in images), [(p.source, p.ok, p.message) for p in images]


def test_a_sheet_without_its_units_table_is_a_failed_source(qgs_app, core_result, tmp_path,
                                                            monkeypatch):
    """Een kaartblad zonder eenhedentabel staat als mislukte bron in het rapport.

    De tekening komt binnen, maar de snede van de eenhedentabel mislukt: dan verdwijnt dat blad
    uit het rapport. Zonder een bronnenregel per kaartblad is er niets dat dat zegt.
    """
    from desktopstudie.core.report_content import profile_image_key, quartair_sheet
    from desktopstudie.qgis import layout as layout_mod
    from desktopstudie.qgis import pipeline

    header = write_png(tmp_path / "legendas" / "quartair_22026_kop.png")
    monkeypatch.setattr(layout_mod, "prepare_zone_legend_images",
                        lambda result, out_dir, client, log=None, should_cancel=None:
                        {profile_image_key("22026"): header})

    pipeline._fetch_zone_legends(core_result, {"https://dov/22026_png": "22026"}, tmp_path, None,
                                 _log(), None)

    sheet = quartair_sheet("22026")
    failed = {p.source: p for p in core_result.provenance if not p.ok}
    assert any(f"kaartblad {sheet}" in source for source in failed), sorted(failed)


def test_a_map_the_service_does_not_deliver_is_in_the_sources_without_project_groups(
        project, core_result, offline_shell, tmp_path, monkeypatch, no_pdf):
    """Een kaart die de dienst niet levert, staat in de bronnenlijst ook als er geen
    projectgroepen zijn.

    Headless bouwt `finish` de lagen alleen voor `studie.qgz`; zonder dit valt een ongeldige laag
    daar stilzwijgend uit en zegt niets in het rapport dat die kaart ontbreekt.
    """
    from qgis.core import QgsRasterLayer

    from desktopstudie.core import catalogue
    from desktopstudie.qgis import layers, pipeline

    real = layers.wms_layer

    def half_broken(entry):
        if entry.id == "ferraris":
            return QgsRasterLayer("", entry.title, "wms")  # ongeldig, zoals een dienst die plat ligt
        return real(entry)

    monkeypatch.setattr(layers, "wms_layer", half_broken)

    pipeline.finish(project, core_result, _meta(), tmp_path, _log(), legends=False,
                    study_groups=False)

    failed = {p.source: p for p in core_result.provenance if not p.ok}
    assert f"Kaartlaag {catalogue.by_id('ferraris').title}" in failed, sorted(failed)


def test_a_failed_pdf_still_leaves_the_project_and_the_geopackage(project, core_result, offline_shell,
                                                                  tmp_path, monkeypatch):
    """De PDF is het laatste product, niet het enige. Loopt de export stuk, dan houdt de gebruiker
    het GeoPackage en het projectbestand - en de melding zegt wat er mis ging."""
    from desktopstudie.qgis import export, pipeline

    def boom(lay, path, **kwargs):
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

    def cancelled(lay, path, **kwargs):
        raise StudyCancelled("afgebroken door de gebruiker")

    monkeypatch.setattr(export, "export_pdf", cancelled)

    with pytest.raises(StudyCancelled):
        pipeline.finish(project, core_result, _meta(), tmp_path, _log(), legends=False)


def test_a_map_that_draws_nothing_here_is_noted_but_not_failed(project, core_result, offline_shell,
                                                               tmp_path, monkeypatch, no_pdf):
    """De Popp-kaart is in Gent wit: het mozaiek heeft daar geen blad. De dienst antwoordde wel, dus
    de bron blijft "ok" - met de reden erbij, zodat het witte blad verklaard is."""
    from desktopstudie.qgis import layout, pipeline

    real = layout.prepare_map_images

    def empty_ferraris(requests, out_dir, client, log=None, should_cancel=None):
        images, _empty = real(requests, out_dir, client, log, should_cancel)
        return images, {"ferraris"}

    monkeypatch.setattr(layout, "prepare_map_images", empty_ferraris)

    out = pipeline.finish(project, core_result, _meta(), tmp_path, _log(), legends=False)

    beeld = next(p for p in out.result.provenance if p.source.startswith("Kaartbeeld Ferraris"))
    assert beeld.ok is True
    assert beeld.message == pipeline.NO_COVERAGE_MESSAGE
    others = [p for p in out.result.provenance
              if p.source.startswith("Kaartbeeld") and p is not beeld]
    assert all(p.message == "" for p in others), [p.source for p in others]


def test_finish_reports_how_long_every_phase_took(project, core_result, offline_shell, tmp_path,
                                                  no_pdf):
    """Een studie die een half uur duurt moet kunnen zeggen WAAR die tijd heen ging. "Het was traag"
    is geen diagnose, en de voortgangsbalk van de plugin heeft dezelfde opsplitsing nodig."""
    from desktopstudie.qgis import pipeline

    out = pipeline.finish(project, core_result, _meta(), tmp_path, _log(), legends=False)

    names = [name for name, _seconds in out.timings]
    # De netwerkhelft (hier alleen de kaartbeelden: geen legenda's, geen quartair) staat vooraan,
    # want die draait in de plugin op de werkthread, vóór de schil het project aanraakt.
    assert names == ["Kaartbeelden", "Relief uit DHMV", "Lagen", "Signaleringen en rapport",
                     "GeoPackage en projectbestand", "Layout", "PDF-export"], names
    assert all(seconds >= 0.0 for _name, seconds in out.timings)
    assert sum(seconds for _name, seconds in out.timings) > 0.0


def test_the_phase_table_is_logged_and_names_the_slowest(project, core_result, offline_shell,
                                                         tmp_path, no_pdf):
    """De tabel hoort in het log te staan, ook als niemand het resultaat uitleest: bij een trage
    run is dat het enige spoor."""
    from desktopstudie.qgis import pipeline

    lines = []
    pipeline.finish(project, core_result, _meta(), tmp_path, _log(lines), legends=False)

    table = [line for line in lines if "fase" in line or " s " in line]
    assert any("Layout" in line for line in table), lines[-12:]


def test_a_run_without_project_groups_builds_the_wms_layers_once(project, core_result,
                                                                 offline_shell, tmp_path,
                                                                 monkeypatch, no_pdf):
    """Een WMS-laag bouwen kost een GetCapabilities, en tegen DOV is dat 2,6 s per kaart - twee
    keer dertig ronden voor niets. Headless kijkt niemand naar het geopende project: dan worden de
    lagen één keer gebouwd, voor het projectbestand dat wél geleverd wordt."""
    from desktopstudie.qgis import layers, pipeline

    built = []
    real = layers.wms_layer

    def counted(entry):
        built.append(entry.id)
        return real(entry)

    monkeypatch.setattr(layers, "wms_layer", counted)

    out = pipeline.finish(project, core_result, _meta(), tmp_path, _log(), legends=False,
                          study_groups=False)

    assert len(built) == len(set(built)), built
    assert out.project_file is not None and out.project_file.exists()
    study = project.layerTreeRoot().findGroup(pipeline.study_group_name("Testproject"))
    titles = [group.name() for group in study.findGroups()]
    assert titles == [layers.ZONE_GROUP, layers.INVESTIGATION_GROUP], titles


def test_a_run_with_project_groups_still_fills_the_open_project(project, core_result, offline_shell,
                                                                tmp_path, no_pdf):
    """In de plugin is dat geopende project juist de plek waar de gebruiker verder werkt."""
    from desktopstudie.qgis import pipeline

    pipeline.finish(project, core_result, _meta(), tmp_path, _log(), legends=False)

    study = project.layerTreeRoot().findGroup(pipeline.study_group_name("Testproject"))
    titles = [group.name() for group in study.findGroups()]
    assert list(pipeline.CHAPTER_GROUPS.values())[0] in titles
