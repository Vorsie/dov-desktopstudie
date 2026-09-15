from __future__ import annotations

import json

from desktopstudie.core import study
from desktopstudie.core.model import StudyZone
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
    from desktopstudie.core.services.http import HttpError

    client = _client()
    client.routes.insert(0, ("typeNames=bodemkaart", HttpError("https://x", 503, "down")))
    result = study.run(StudyZone(ring=gent_ring, name="z"), study.Settings(n_section_points=2), client, tmp_path)
    failed = [p for p in result.provenance if not p.ok]
    assert failed and failed[0].source.startswith("Bodemkaart")
    assert any(s.code == "bron_niet_beschikbaar" for s in result.signaleringen)
    assert result.section is not None  # the rest still ran
