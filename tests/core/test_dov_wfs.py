from __future__ import annotations

import json

import pytest

from desktopstudie.core.logging_util import Log
from desktopstudie.core.services.dov_wfs import DovWfs, feature_xy
from tests.core.conftest import FixtureClient, fixture_json

ZONE = "POLYGON((104226 192406,104426 192406,104426 192606,104226 192606,104226 192406))"


def test_geometry_field_comes_from_describe_feature_type_and_is_cached():
    client = FixtureClient([("request=DescribeFeatureType", "wfs_describe_tertiair_50k.json")])
    wfs = DovWfs(client)
    assert wfs.geometry_field("neo_paleo:tertiair_50k") == "shape"
    assert wfs.geometry_field("neo_paleo:tertiair_50k") == "shape"
    assert len(client.calls) == 1


def test_geometry_field_raises_when_describe_has_no_gml_property():
    client = FixtureClient([
        ("request=DescribeFeatureType", b'{"featureTypes":[{"properties":[{"name":"id","type":"xsd:int"}]}]}'),
    ])
    wfs = DovWfs(client)
    with pytest.raises(ValueError):
        wfs.geometry_field("dov-pub:GeenGeometrie")


def test_within_distance_builds_dwithin_filter_and_pages():
    client = FixtureClient([
        ("request=DescribeFeatureType", "wfs_describe_sonderingen.json"),
        ("startIndex=5", "wfs_sonderingen_page2.json"),
        ("startIndex=0", "wfs_sonderingen_dwithin.json"),
    ])
    wfs = DovWfs(client, page_size=5)
    feats = wfs.within_distance("dov-pub:Sonderingen", ZONE, 500, max_features=10)
    assert len(feats) == 10
    assert "CQL_FILTER=DWITHIN%28geom%2CPOLYGON" in client.calls[1]
    assert "BBOX=" not in client.calls[1]  # never combine BBOX and CQL_FILTER
    assert feats[0]["properties"]["sondeernummer"]


def test_truncation_is_recorded_when_max_features_caps_the_result():
    client = FixtureClient([
        ("request=DescribeFeatureType", "wfs_describe_sonderingen.json"),
        ("startIndex=0", "wfs_sonderingen_dwithin.json"),
    ])
    wfs = DovWfs(client, page_size=5)
    feats = wfs.within_distance("dov-pub:Sonderingen", ZONE, 500, max_features=5)
    assert len(feats) == 5
    assert wfs.truncations == [("dov-pub:Sonderingen", 5, 167)]


def test_duplicate_ids_across_pages_are_dropped():
    # numberMatched patched to equal the raw fetched total (10), so this scenario is genuinely
    # NOT truncated: the server handed over everything it claims to have, and de-duplication
    # alone explains the drop from 10 fetched to 5 unique.
    payload = fixture_json("wfs_sonderingen_dwithin.json")
    payload["numberMatched"] = 10
    body = json.dumps(payload).encode("utf-8")
    client = FixtureClient([
        ("request=DescribeFeatureType", "wfs_describe_sonderingen.json"),
        # both pages resolve to the same body, so page 2 repeats page 1's feature ids
        ("startIndex=5", body),
        ("startIndex=0", body),
    ])
    messages: list[str] = []
    wfs = DovWfs(client, page_size=5, log=Log("test", sink=messages.append, level="DEBUG"))
    feats = wfs.within_distance("dov-pub:Sonderingen", ZONE, 500, max_features=10)
    assert len(feats) == 5
    assert wfs.truncations == []
    assert any("dubbele features" in m for m in messages)


def test_hybrid_truncation_and_duplicates_records_truncation():
    # both pages resolve to the ORIGINAL fixture (numberMatched=167 untouched), so duplicates
    # drop the unique count to 5 AND the server genuinely withheld data (only 10 of 167 fetched)
    # -- truncation and de-duplication must both be reported, independently of each other.
    client = FixtureClient([
        ("request=DescribeFeatureType", "wfs_describe_sonderingen.json"),
        ("startIndex=5", "wfs_sonderingen_dwithin.json"),
        ("startIndex=0", "wfs_sonderingen_dwithin.json"),
    ])
    messages: list[str] = []
    wfs = DovWfs(client, page_size=5, log=Log("test", sink=messages.append, level="DEBUG"))
    feats = wfs.within_distance("dov-pub:Sonderingen", ZONE, 500, max_features=10)
    assert len(feats) == 5
    assert wfs.truncations == [("dov-pub:Sonderingen", 5, 167)]
    assert any("dubbele features" in m for m in messages)


def test_intersecting_uses_layer_specific_geometry_field():
    client = FixtureClient([
        ("request=DescribeFeatureType", "wfs_describe_tertiair_50k.json"),
        ("request=GetFeature", "wfs_tertiair_50k_intersects.json"),
    ])
    feats = DovWfs(client).intersecting("neo_paleo:tertiair_50k", ZONE)
    assert "INTERSECTS%28shape%2C" in client.calls[1]
    assert feats[0]["properties"]["formatie"]


def test_feature_xy_reads_point_geometry():
    feat = {"geometry": {"type": "Point", "coordinates": [104007.0, 192682.0]}, "properties": {}}
    assert feature_xy(feat) == (104007.0, 192682.0)


def test_feature_xy_raises_when_geometry_is_missing():
    feat = {"id": "Sonderingen.1", "geometry": None, "properties": {}}
    with pytest.raises(ValueError):
        feature_xy(feat)


@pytest.mark.live
def test_live_paging_returns_all_matches():
    from desktopstudie.core.services.http import HttpClient

    wfs = DovWfs(HttpClient(), page_size=100)
    feats = wfs.within_distance("dov-pub:Sonderingen", ZONE, 500)
    assert len(feats) > 100
    assert len({f["id"] for f in feats}) == len(feats)
    assert len(feats) > wfs.page_size
