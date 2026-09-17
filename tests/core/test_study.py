from __future__ import annotations

import json
import urllib.parse
from typing import List, Tuple

import pytest

from desktopstudie.core import geometry, study
from desktopstudie.core.logging_util import Log
from desktopstudie.core.model import StudyZone
from desktopstudie.core.report_content import ReportMeta, TextPage, build_report
from desktopstudie.core.section import section_line
from desktopstudie.core.services.http import HttpError
from tests.core.conftest import FixtureClient


def _client():
    """Every service the orchestrator touches, routed to a recorded answer. The first substring
    match wins, so the two DescribeFeatureType routes come first: they would otherwise be caught
    by the GetFeature routes, which match on `typeNames=` alone."""
    return FixtureClient([
        ("request=DescribeFeatureType&typeNames=neo_paleo", "wfs_describe_tertiair_50k.json"),
        ("request=DescribeFeatureType", "wfs_describe_sonderingen.json"),
        ("typeNames=dov-pub%3ASonderingen", "wfs_sonderingen_dwithin.json"),
        ("typeNames=dov-pub%3ABoringen", "wfs_boringen_dwithin.json"),
        ("typeNames=interpretaties%3Alithologische_beschrijvingen", "wfs_lithologische_beschrijvingen_dwithin.json"),
        ("typeNames=interpretaties%3Agecodeerde_lithologie", "wfs_gecodeerde_lithologie_dwithin.json"),
        ("typeNames=gw_meetnetten", "wfs_grondwaterlocaties_dwithin.json"),
        ("typeNames=bodemkaart", "wfs_bodemtypes_intersects.json"),
        ("typeNames=quartair%3Aquartair_samengesteld", "wfs_quartair_samengesteld_intersects.json"),
        ("typeNames=quartair%3Aquartair_200k", "wfs_quartair_200k_intersects.json"),
        ("typeNames=dov-pub%3AQuartair_Isopachen", "wfs_quartair_isopachen_intersects.json"),
        ("typeNames=neo_paleo", "wfs_tertiair_50k_intersects.json"),
        ("typeNames=hcov", "wfs_hcov_0100_vk_intersects.json"),
        ("typeNames=gw_bescherming", "wfs_gwkwb_kwbschaal_intersects.json"),
        ("typeNames=ovam", "wfs_ovam_uitspraak_intersects.json"),
        ("typeNames=plastische_gronden", "wfs_indexplastisch_intersects.json"),
        ("typeNames=erosie", "wfs_erosie_2014_intersects.json"),
        ("typeNames=grondverschuivingen%3Agrndversch_gevoeligh", "wfs_grndversch_gevoeligh_intersects.json"),
        ("typeNames=grondverschuivingen%3Agrndversch_gekarteerd", "wfs_grndversch_gekarteerd_intersects.json"),
        ("typeNames=pfas", "wfs_pfas_no_regret_intersects.json"),
        ("data/sondering/", "sondering_1965-039716.xml"),
        ("data/interpretatie/", "interpretatie_2016-252456.xml"),
        ("data/filter/", "filter_1985-007948.xml"),
        ("profielbevraging", "vb_profile_g3dv3_F.json"),
        ("doorprik/g3dv3_F", "vb_g3dv3_F.json"),
        ("doorprik/g3dv3_L", "vb_g3dv3_L.json"),
        ("doorprik/g3dv3_P", "vb_g3dv3_P.json"),
        ("doorprik/hcovv2_S", "vb_hcovv2_S.json"),
        ("gebieden_fluviaal", "watertoets_fluviaal_hit.json"),
        ("gebieden_pluviaal", "watertoets_pluviaal_empty.json"),
    ])


def test_run_produces_result_json_and_figures(gent_ring, tmp_path):
    zone = StudyZone(ring=gent_ring, name="Gent test")
    settings = study.Settings(n_cpt_figures=2, n_borehole_figures=1, n_section_points=3)
    messages = []
    result = study.run(zone, settings, _client(), tmp_path, progress=lambda f, m: messages.append((f, m)))
    assert result.cpts and result.cpts[0].distance_m <= result.cpts[-1].distance_m
    assert sum(1 for c in result.cpts if c.profile) == 2
    assert result.boreholes and any(b.lithology for b in result.boreholes)
    assert result.gw_filters and any(f.latest for f in result.gw_filters)
    assert set(result.virtual_boreholes) == {"g3dv3_F", "g3dv3_L", "g3dv3_P", "hcovv2_S"}
    assert result.section and len(result.section.boreholes) == 3
    assert result.section.profile is not None
    assert {mf.map_id for mf in result.map_facts} >= {"bodemkaart", "tertiair", "watertoets_fluviaal",
                                                      "pfas_no_regret", "grondverschuiving_gekarteerd"}
    codes = [s.code for s in result.signaleringen]
    assert "overstroming" in codes
    assert "pfas_no_regret" in codes
    # The recorded WFS fixtures were captured with count=5 while the server reported far more
    # matches, so the run must SAY the lists are cut off rather than show a short table silently.
    assert "wfs_afgekapt" in codes
    assert any("dov-pub:Sonderingen" in s.fact for s in result.signaleringen if s.code == "wfs_afgekapt")
    assert (tmp_path / "data" / "studie.json").exists()
    assert (tmp_path / "figuren" / "section.png").exists()
    assert "vb_g3dv3_F" in result.figures
    # Figure paths are relative to the output directory and use forward slashes, so the JSON
    # travels from a Windows run to any other machine unchanged.
    assert result.figures["section"] == "figuren/section.png"
    assert all("\\" not in p and not p.startswith("/") for p in result.figures.values())
    assert all(p.ok for p in result.provenance)
    assert messages[-1][0] == 1.0
    data = json.loads((tmp_path / "data" / "studie.json").read_text(encoding="utf-8"))
    assert data["summary"]["n_cpts"] == len(result.cpts)


def test_failing_source_is_isolated_and_reported(gent_ring, tmp_path):
    client = _client()
    client.routes.insert(0, ("typeNames=bodemkaart", HttpError("https://x", 503, "down")))
    result = study.run(StudyZone(ring=gent_ring, name="z"), study.Settings(n_section_points=2), client, tmp_path)
    failed = [p for p in result.provenance if not p.ok]
    assert failed and failed[0].source.startswith("Bodemkaart")
    assert any(s.code == "bron_niet_beschikbaar" for s in result.signaleringen)
    assert result.section is not None  # the rest still ran


def _outside_the_models_client():
    """Every doorprik answers "no layers" (HTTP 200 with an empty data[], what DOV returns outside
    Flanders) and the profile query is down: nothing to draw a section from anywhere."""
    client = _client()
    client.routes.insert(0, ("profielbevraging", HttpError("https://x/profiel", 500, "down")))
    client.routes.insert(0, ("doorprik", b'{"data": [], "layers": []}'))
    return client


def test_a_point_outside_the_models_reports_empty_sources_instead_of_empty_figures(gent_ring, tmp_path):
    # "Nooit stil een leeg resultaat teruggeven": a virtual borehole without layers and a section
    # without geology are FAILED sources in the report, not ok sources with an empty picture.
    result = study.run(StudyZone(ring=gent_ring, name="z"), study.Settings(n_section_points=3),
                       _outside_the_models_client(), tmp_path)
    failed = {p.source: p.message for p in result.provenance if not p.ok}
    assert {f"Virtuele boring {m}" for m in ("g3dv3_F", "g3dv3_L", "g3dv3_P", "hcovv2_S")} <= set(failed)
    assert all("geen lagen op dit punt" in failed[f"Virtuele boring {m}"]
               for m in ("g3dv3_F", "g3dv3_L", "g3dv3_P", "hcovv2_S"))
    assert "profiel niet beschikbaar" in failed["Doorsnede - profielbevraging"]
    assert "geen modellagen langs de lijn" in failed["Doorsnede (virtuele boringen langs de lijn)"]
    assert result.virtual_boreholes == {}  # an empty borehole is not stored
    assert result.section is None
    assert "section" not in result.figures
    assert not (tmp_path / "figuren" / "section.png").exists()
    # the report says so in words, in the chapter that would otherwise show an empty column
    report = build_report(result, ReportMeta(project="P", author="A", company="C"))
    assert any(isinstance(page, TextPage) and "niet beschikbaar" in page.html
               for page in report.chapters[3].pages)
    # exit code 3 in run_core keys off exactly this count, and it is unchanged: failed is failed
    assert result.summary()["n_sources_failed"] == len(failed)
    assert any(s.code == "bron_niet_beschikbaar" for s in result.signaleringen)


def test_failed_section_points_are_reported_as_a_signalering(gent_ring, tmp_path):
    # A section drawn from fewer columns than were asked for is thinner than it looks; the gap has
    # to be named, not left to the reader.
    client = _client()
    line = section_line(StudyZone(ring=gent_ring, name="z"), study.Settings().section_extension_m)
    first = geometry.sample_line(line[0], line[1], 3)[0]
    client.routes.insert(0, (f"x={first[0]:.2f}", HttpError("https://x/doorprik", 500, "down")))
    result = study.run(StudyZone(ring=gent_ring, name="z"), study.Settings(n_section_points=3),
                       client, tmp_path)
    assert result.section is not None and result.section.failed_points == 1
    sigs = [s for s in result.signaleringen if s.code == "doorsnede_onvolledig"]
    assert len(sigs) == 1
    assert sigs[0].fact.startswith("1 van 3 doorprik-punten mislukt")
    assert sigs[0].severity == "info"


def _warnings():
    """A log that only collects WARNING and above, so a test can count what was reported."""
    messages: List[str] = []
    return messages, Log("study", sink=messages.append, level="WARNING")


def test_one_failing_fiche_costs_only_that_item(gent_ring, tmp_path):
    # "Elke bron faalt geisoleerd" applies inside a stage too: one sondering whose fiche is down
    # must not take the other four profiles - nor the Sonderingen source itself - down with it.
    runs = []
    for i in range(3):  # three runs: the thread pool must not make the outcome depend on timing
        messages, log = _warnings()
        client = _client()
        client.routes.insert(0, ("sondering/1977-011307", HttpError("https://x/sondering", 500, "down")))
        result = study.run(StudyZone(ring=gent_ring, name="z"), study.Settings(n_section_points=2),
                           client, tmp_path / f"run{i}", log=log)
        sonderingen = [p for p in result.provenance if p.source == "Sonderingen"]
        runs.append((sonderingen[0].ok, sum(1 for c in result.cpts if c.profile),
                     len([m for m in messages if "sondering niet opgehaald" in m])))
    assert runs[0] == (True, 4, 1)  # the stage stays ok, four profiles survive, one warning
    assert runs[0] == runs[1] == runs[2], f"non-deterministic across runs: {runs}"


def _gfi_centres(client) -> List[Tuple[float, float]]:
    """The (x, y) each GetFeatureInfo call asked about, read back from its bbox."""
    centres = []
    for url in client.calls:
        query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        if query.get("request") == ["GetFeatureInfo"] and "gebieden_fluviaal" in url:
            x0, y0, x1, y1 = (float(v) for v in query["bbox"][0].split(","))
            centres.append(((x0 + x1) / 2.0, (y0 + y1) / 2.0))
    return centres


def test_feature_info_points_are_spread_around_the_whole_ring(tmp_path):
    # A 64-vertex circle: sampling ring[:8] would take eight neighbouring vertices - a single arc -
    # so a flood zone touching the far side of the zone would never be asked about.
    ring = geometry.buffer_point(104326.0, 192506.0, 100.0, n=64)
    client = _client()
    study.run(StudyZone(ring=ring, name="rond"), study.Settings(n_section_points=2), client, tmp_path)
    centres = _gfi_centres(client)
    cx, cy = geometry.centroid(ring)
    quadrants = {(x > cx, y > cy) for x, y in centres}
    assert len(centres) == 9  # the representative point plus eight ring vertices
    assert quadrants == {(True, True), (True, False), (False, True), (False, False)}


def test_cancelling_between_stages_raises_and_writes_nothing(gent_ring, tmp_path):
    seen = []
    with pytest.raises(study.StudyCancelled):
        study.run(StudyZone(ring=gent_ring, name="z"), study.Settings(n_section_points=2), _client(),
                  tmp_path, progress=lambda f, m: seen.append(m), should_cancel=lambda: len(seen) >= 2)
    assert seen[:2] == ["Sonderingen", "Boringen"]
    assert not (tmp_path / "data" / "studie.json").exists()


def test_map_ids_limits_the_maps_that_are_fetched(gent_ring, tmp_path):
    result = study.run(StudyZone(ring=gent_ring, name="z"),
                       study.Settings(n_section_points=2, map_ids=["bodemkaart"]), _client(), tmp_path)
    assert [mf.map_id for mf in result.map_facts] == ["bodemkaart"]


def test_the_chosen_maps_travel_with_the_study(gent_ring, tmp_path):
    """De keuze uit de kaartenchecklist hoort bij het resultaat, niet alleen bij de instellingen:
    de schil leest er haar lagen, legenda's en kaartbeelden uit, en een lezer van studie.json ziet
    zo welke kaarten de studie gedekt heeft."""
    import json

    result = study.run(StudyZone(ring=gent_ring, name="z"),
                       study.Settings(n_section_points=2, map_ids=["bodemkaart"]), _client(), tmp_path)

    assert result.map_ids == ["bodemkaart"]
    data = json.loads((tmp_path / "data" / "studie.json").read_text(encoding="utf-8"))
    assert data["map_ids"] == ["bodemkaart"]


def test_without_a_choice_the_study_records_no_map_selection(gent_ring, tmp_path):
    """Zonder keuze blijven alle ingeschakelde kaarten in het rapport, en dat is wat `None` zegt -
    een lijst van alle ids zou een keuze suggereren die de gebruiker niet gemaakt heeft."""
    result = study.run(StudyZone(ring=gent_ring, name="z"), study.Settings(n_section_points=2),
                       _client(), tmp_path)

    assert result.map_ids is None


def test_with_profile_false_skips_the_profile_query(gent_ring, tmp_path):
    client = _client()
    result = study.run(StudyZone(ring=gent_ring, name="z"),
                       study.Settings(n_section_points=2, with_profile=False), client, tmp_path)
    assert result.section is not None and result.section.profile is None
    assert not any("profielbevraging" in url for url in client.calls)


def test_a_json_that_cannot_be_written_is_reported_as_a_failed_source(gent_ring, tmp_path):
    (tmp_path / "data").write_text("in the way", encoding="utf-8")  # a file where the dir must go
    result = study.run(StudyZone(ring=gent_ring, name="z"), study.Settings(n_section_points=2),
                       _client(), tmp_path)
    failed = [p for p in result.provenance if p.source == "studie.json"]
    assert failed and not failed[0].ok


def _sonderingen_payload(rows) -> bytes:
    features = [{"type": "Feature", "id": f"s{i}", "geometry": {"type": "Point", "coordinates": [x, y]},
                 "properties": {"sondeernummer": f"S{i}", "fiche": "https://dov/data/sondering/1965-039716",
                                "Z_mTAW": 10.0, "gemeente": gemeente}}
                for i, (x, y, gemeente) in enumerate(rows)]
    payload = {"type": "FeatureCollection", "features": features,
               "numberMatched": len(features), "numberReturned": len(features)}
    return json.dumps(payload).encode("utf-8")


def test_municipality_comes_from_the_nearest_feature_that_names_one(gent_ring, tmp_path):
    # The WFS answer is unordered, so "the first feature with a gemeente" can name a town on the
    # far edge of the search radius; the zone's own municipality is the nearest one.
    client = _client()
    client.routes.insert(0, ("typeNames=dov-pub%3ASonderingen", _sonderingen_payload([
        (104326.0 + 450.0, 192506.0, "Merelbeke"),  # first in the answer, but 350 m from the zone
        (104326.0, 192506.0, "Gent"),               # inside the zone
    ])))
    result = study.run(StudyZone(ring=gent_ring, name="z"), study.Settings(n_section_points=2),
                       client, tmp_path)
    assert result.municipality == "Gent"


def test_a_long_failure_message_is_trimmed_in_the_provenance(gent_ring, tmp_path):
    client = _client()
    client.routes.insert(0, ("typeNames=bodemkaart", HttpError("https://x/wfs?a=1", 500, "x" * 1000)))
    result = study.run(StudyZone(ring=gent_ring, name="z"), study.Settings(n_section_points=2),
                       client, tmp_path)
    failed = [p for p in result.provenance if not p.ok]
    assert failed and len(failed[0].message) <= 220  # "HttpError: " plus 200 characters of text


def test_the_orchestrator_signals_survive_a_second_pass_of_the_rules(gent_ring):
    """De schil draait `checks.run_all` opnieuw zodra het reliëf binnen is. Die regels kennen de
    afkapping van een WFS en een onvolledige doorsnede niet - die weet alleen de orchestrator -
    dus moeten ze apart uit het resultaat te halen zijn, of ze verdwijnen bij die tweede pas."""
    from desktopstudie.core.model import Signalering, StudyResult

    result = StudyResult(zone=StudyZone(ring=gent_ring, name="z"), created_at="2026-09-15T10:00:00")
    result.signaleringen = [
        Signalering("wfs_afgekapt", "dov-pub:Sonderingen: 5 van 90 objecten opgehaald.", "DOV WFS", "x",
                    severity="info"),
        Signalering("overstroming", "klasse C", "VMM", "y"),
        Signalering("doorsnede_onvolledig", "1 van 3 doorprik-punten mislukt.", "DOV", "z", severity="info"),
    ]

    kept = study.orchestrator_signals(result)

    assert [s.code for s in kept] == ["wfs_afgekapt", "doorsnede_onvolledig"]
    assert study.orchestrator_signals(StudyResult(zone=StudyZone(ring=gent_ring, name="z"),
                                                 created_at="2026-09-15T10:00:00")) == []


def test_a_fiche_gets_a_shorter_breath_than_a_whole_table(gent_ring, tmp_path):
    """Een fiche is één item van honderd: drie keer een volle minuut wachten op een record dat
    plat ligt, kost de studie haar tijd. De WFS-oproep die een hele tabel levert houdt de
    geduldige standaardwaarden."""
    client = _client()
    study.run(StudyZone(ring=gent_ring, name="z"), study.Settings(n_section_points=2), client, tmp_path)

    fiches = [(url, timeout, retries) for url, timeout, retries in client.options if url.endswith(".xml")]
    assert fiches, client.calls[:5]
    assert all((timeout, retries) == (study.ITEM_TIMEOUT_S, study.ITEM_RETRIES) for _u, timeout, retries in fiches)
    wfs = [(timeout, retries) for url, timeout, retries in client.options if "request=GetFeature" in url]
    assert wfs and all(option == (None, None) for option in wfs)


def test_a_failing_map_costs_that_map_and_leaves_the_sources_in_order(gent_ring, tmp_path):
    """Eén kaart die faalt mag de rest niet meenemen, en de bronnenlijst hoort de volgorde van de
    catalogus te volgen - anders staat het rapport bij elke run in een andere volgorde. Dit gold
    al toen de feiten na elkaar werden opgehaald; de test houdt het overeind nu ze parallel
    binnenkomen en de threads in willekeurige volgorde klaar zijn."""
    from desktopstudie.core import catalogue

    client = _client()
    client.routes.insert(0, ("typeNames=erosie", HttpError("https://dov/wfs?typeNames=erosie", 500, "down")))

    result = study.run(StudyZone(ring=gent_ring, name="z"), study.Settings(n_section_points=2),
                       client, tmp_path)

    assert {mf.map_id for mf in result.map_facts} >= {"bodemkaart", "tertiair", "ovam"}
    assert "erosie" not in {mf.map_id for mf in result.map_facts}
    failed = [p for p in result.provenance if not p.ok]
    assert [p.source for p in failed] == ["Potentiele bodemerosiekaart per perceel (2014) (feiten)"]
    facts_order = [p.source for p in result.provenance if p.source.endswith("(feiten)")]
    expected = [f"{e.title} (feiten)" for e in catalogue.entries() if e.fact_mode is not None]
    assert facts_order == expected


def test_the_json_source_is_recorded_by_its_relative_path(gent_ring, tmp_path):
    """Een absoluut Windows-pad in de bronnentabel zet de map van de maker in het rapport."""
    result = study.run(StudyZone(ring=gent_ring, name="z"), study.Settings(n_section_points=2),
                       _client(), tmp_path)

    json_source = [p for p in result.provenance if p.source == "studie.json"]
    assert json_source and json_source[0].url == "data/studie.json"


def test_a_dead_getfeatureinfo_service_is_not_reported_as_an_empty_zone(gent_ring, tmp_path):
    """Elk punt van een GetFeatureInfo-kaart faalt apart, maar als ALLE punten falen is de kaart
    niet leeg - ze is onbereikbaar. "Geen kaarteenheden binnen de zone" zou van een platte
    watertoets-dienst een perceel zonder overstromingsrisico maken."""
    client = _client()
    client.routes.insert(0, ("gebieden_pluviaal",
                             HttpError("https://inspirepub.waterinfo.be/pluviaal", 503, "down")))

    result = study.run(StudyZone(ring=gent_ring, name="z"), study.Settings(n_section_points=2),
                       client, tmp_path)

    assert "watertoets_pluviaal" not in {mf.map_id for mf in result.map_facts}
    failed = [p for p in result.provenance if not p.ok and "pluviaal" in p.source]
    assert failed, [p.source for p in result.provenance if not p.ok]
    assert any(s.code == "bron_niet_beschikbaar" for s in result.signaleringen)


def test_compact_layout_is_off_by_default():
    """De compacte opmaak is een keuze, geen standaard: wie niets kiest krijgt de voorspelbare
    opmaak van altijd."""
    from desktopstudie.core.study import Settings

    assert Settings().compact is False
    assert Settings(compact=True).compact is True
