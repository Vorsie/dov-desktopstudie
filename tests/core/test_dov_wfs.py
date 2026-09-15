from __future__ import annotations

import pytest

from desktopstudie.core.services.dov_wfs import DovWfs, feature_xy
from tests.core.conftest import FixtureClient

ZONE = "POLYGON((104226 192406,104426 192406,104426 192606,104226 192606,104226 192406))"


def test_geometry_field_comes_from_describe_feature_type_and_is_cached():
    client = FixtureClient([("request=DescribeFeatureType", "wfs_describe_tertiair_50k.json")])
    wfs = DovWfs(client)
    assert wfs.geometry_field("neo_paleo:tertiair_50k") == "shape"
    assert wfs.geometry_field("neo_paleo:tertiair_50k") == "shape"
    assert len(client.calls) == 1


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


@pytest.mark.live
def test_live_paging_returns_all_matches():
    from desktopstudie.core.services.http import HttpClient

    feats = DovWfs(HttpClient(), page_size=100).within_distance("dov-pub:Sonderingen", ZONE, 500)
    assert len(feats) > 100
