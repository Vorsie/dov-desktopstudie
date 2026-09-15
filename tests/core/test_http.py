from __future__ import annotations

import pytest

from desktopstudie.core.services import http
from tests.core.conftest import FixtureClient


def test_build_url_encodes_params_and_keeps_existing_query():
    url = http.build_url("https://x.be/wfs?service=WFS", {"CQL_FILTER": "DWITHIN(geom,POLYGON((1 2,3 4)),5,meters)"})
    assert url == "https://x.be/wfs?service=WFS&CQL_FILTER=DWITHIN%28geom%2CPOLYGON%28%281%202%2C3%204%29%29%2C5%2Cmeters%29"


def test_get_retries_on_server_error_then_succeeds():
    attempts = []

    def fetch(url, timeout, user_agent):
        attempts.append(url)
        if len(attempts) < 3:
            raise http.HttpError(url, 503, "busy")
        return b"ok"

    client = http.HttpClient(fetch=fetch, retries=2, sleep=lambda s: None)
    assert client.get("https://x.be/a") == b"ok"
    assert len(attempts) == 3


def test_get_does_not_retry_client_errors():
    def fetch(url, timeout, user_agent):
        raise http.HttpError(url, 404, "nope")

    client = http.HttpClient(fetch=fetch, retries=3, sleep=lambda s: None)
    with pytest.raises(http.HttpError) as exc:
        client.get("https://x.be/a")
    assert exc.value.status == 404


def test_disk_cache_serves_second_call_without_fetch(tmp_path):
    calls = []

    def fetch(url, timeout, user_agent):
        calls.append(url)
        return b'{"a": 1}'

    client = http.HttpClient(cache_dir=tmp_path, fetch=fetch)
    assert client.get_json("https://x.be/a", {"q": "1"}) == {"a": 1}
    assert client.get_json("https://x.be/a", {"q": "1"}) == {"a": 1}
    assert len(calls) == 1
    assert len(list(tmp_path.glob("*.bin"))) == 1


def test_fixture_client_routes_records_and_raises_like_http_client():
    client = FixtureClient([("boom", http.HttpError("https://x.be/boom", 503, "down")), ("hit", b'{"ok": true}')])
    assert client.get_json("https://x.be/hit", {"q": "1"}) == {"ok": True}
    assert client.calls == ["https://x.be/hit?q=1"] and client.matched == ["hit"]
    with pytest.raises(http.HttpError):
        client.get("https://x.be/boom")
    with pytest.raises(AssertionError):
        client.get("https://x.be/unknown")
