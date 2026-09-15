from __future__ import annotations

import contextlib
import socketserver
import threading

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
    attempts = []

    def fetch(url, timeout, user_agent):
        attempts.append(url)
        raise http.HttpError(url, 404, "nope")

    client = http.HttpClient(fetch=fetch, retries=3, sleep=lambda s: None)
    with pytest.raises(http.HttpError) as exc:
        client.get("https://x.be/a")
    assert exc.value.status == 404
    assert len(attempts) == 1


def test_429_is_retried_then_succeeds():
    attempts = []

    def fetch(url, timeout, user_agent):
        attempts.append(url)
        if len(attempts) < 2:
            raise http.HttpError(url, 429, "too many requests")
        return b"ok"

    client = http.HttpClient(fetch=fetch, retries=2, sleep=lambda s: None)
    assert client.get("https://x.be/a") == b"ok"
    assert len(attempts) == 2


def test_retry_exhaustion_raises_the_last_http_error():
    def fetch(url, timeout, user_agent):
        raise http.HttpError(url, 503, "busy")

    client = http.HttpClient(fetch=fetch, retries=2, sleep=lambda s: None)
    with pytest.raises(http.HttpError) as exc:
        client.get("https://x.be/a")
    assert exc.value.status == 503


def test_backoff_grows_with_attempt_number():
    sleeps = []

    def fetch(url, timeout, user_agent):
        raise http.HttpError(url, 503, "busy")

    client = http.HttpClient(fetch=fetch, retries=2, sleep=sleeps.append)
    with pytest.raises(http.HttpError):
        client.get("https://x.be/a")
    assert sleeps == [1.5, 3.0]


def test_disk_cache_serves_repeat_calls_and_keys_cache_by_params(tmp_path):
    calls = []

    def fetch(url, timeout, user_agent):
        calls.append(url)
        return b'{"a": 1}'

    client = http.HttpClient(cache_dir=tmp_path, fetch=fetch)
    assert client.get_json("https://x.be/a", {"q": "1"}) == {"a": 1}
    assert client.get_json("https://x.be/a", {"q": "1"}) == {"a": 1}
    assert len(calls) == 1
    assert len(list(tmp_path.glob("*.bin"))) == 1

    assert client.get_json("https://x.be/a", {"q": "2"}) == {"a": 1}
    assert len(calls) == 2
    assert len(list(tmp_path.glob("*.bin"))) == 2


def test_cache_mode_refresh_refetches_and_overwrites(tmp_path):
    calls = []

    def fetch(url, timeout, user_agent):
        calls.append(url)
        return f'{{"n": {len(calls)}}}'.encode()

    client = http.HttpClient(cache_dir=tmp_path, fetch=fetch, cache_mode="refresh")
    assert client.get_json("https://x.be/a") == {"n": 1}
    assert client.get_json("https://x.be/a") == {"n": 2}
    assert len(calls) == 2
    assert len(list(tmp_path.glob("*.bin"))) == 1


def test_cache_mode_off_never_writes_a_file(tmp_path):
    def fetch(url, timeout, user_agent):
        return b'{"a": 1}'

    client = http.HttpClient(cache_dir=tmp_path, fetch=fetch, cache_mode="off")
    client.get_json("https://x.be/a")
    assert list(tmp_path.glob("*.bin")) == []


def test_unknown_cache_mode_raises_value_error():
    with pytest.raises(ValueError):
        http.HttpClient(cache_mode="bogus")


def test_http_error_str_uses_dutch_network_error_text_when_status_is_none():
    assert str(http.HttpError("https://x.be/a", None, "x")).startswith("netwerkfout")


GETFEATURE_URL = ("https://www.dov.vlaanderen.be/geoserver/wfs?service=WFS&version=2.0.0&"
                  "request=GetFeature&typeNames=dov-pub%3ASonderingen&outputFormat=application%2Fjson&"
                  "CQL_FILTER=DWITHIN%28geom%2CPOLYGON%28%28104226%20192406%2C104426%20192406%29%29%2C500%2Cmeters%29")


def test_http_error_text_names_the_request_without_the_whole_query_string():
    # A DOV GetFeature URL carries the entire CQL polygon; repeating it in every log line and in
    # the provenance message drowns the failure itself.
    err = http.HttpError(GETFEATURE_URL, 500, "busy")
    assert str(err) == ("HTTP 500 voor https://www.dov.vlaanderen.be/geoserver/wfs "
                        "(GetFeature dov-pub:Sonderingen): busy")
    assert "CQL_FILTER" not in str(err) and "?" not in str(err)
    assert err.url == GETFEATURE_URL  # the full URL stays available for whoever needs to retry it


def test_http_error_text_of_a_plain_url_is_the_url_itself():
    assert str(http.HttpError("https://services.dov.vlaanderen.be/doorprik/g3dv3_F", 404, "weg")) == (
        "HTTP 404 voor https://services.dov.vlaanderen.be/doorprik/g3dv3_F: weg")


def test_get_json_raises_http_error_on_non_json_body():
    def fetch(url, timeout, user_agent):
        return b"<ServiceExceptionReport/>"

    client = http.HttpClient(fetch=fetch)
    with pytest.raises(http.HttpError) as exc:
        client.get_json("https://x.be/wfs")
    assert exc.value.status == 200
    assert "geen JSON" in str(exc.value)


def test_fixture_client_routes_records_and_raises_like_http_client():
    client = FixtureClient([("boom", http.HttpError("https://x.be/boom", 503, "down")), ("hit", b'{"ok": true}')])
    assert client.get_json("https://x.be/hit", {"q": "1"}) == {"ok": True}
    assert client.calls == ["https://x.be/hit?q=1"] and client.matched == ["hit"]
    with pytest.raises(http.HttpError):
        client.get("https://x.be/boom")
    with pytest.raises(AssertionError):
        client.get("https://x.be/unknown")


@contextlib.contextmanager
def _tcp_server(handler_cls):
    """Spins up a real TCP server on an ephemeral 127.0.0.1 port so default_fetch exercises real
    socket/http.client failure modes (truncated body, reset connection) that no mock reproduces."""
    server = socketserver.TCPServer(("127.0.0.1", 0), handler_cls)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _counting_handler(counter, body=None):
    class Handler(socketserver.BaseRequestHandler):
        def handle(self):
            counter.append(1)
            self.request.recv(65536)
            if body is not None:
                self.request.sendall(body)
    return Handler


def test_default_fetch_surfaces_a_truncated_body_and_the_client_retries_it():
    truncated = b"HTTP/1.1 200 OK\r\nContent-Length: 100\r\n\r\nhello"

    solo = []
    with _tcp_server(_counting_handler(solo, truncated)) as url:
        with pytest.raises(http.HttpError) as exc:
            http.default_fetch(url, timeout=2.0, user_agent="test")
        assert exc.value.status is None

    attempts = []
    with _tcp_server(_counting_handler(attempts, truncated)) as url:
        client = http.HttpClient(fetch=http.default_fetch, retries=1, sleep=lambda s: None, timeout=2.0)
        with pytest.raises(http.HttpError):
            client.get(url)
    assert len(attempts) == 2


def test_default_fetch_surfaces_a_reset_connection_and_the_client_retries_it():
    solo = []
    with _tcp_server(_counting_handler(solo)) as url:
        with pytest.raises(http.HttpError) as exc:
            http.default_fetch(url, timeout=2.0, user_agent="test")
        assert exc.value.status is None

    attempts = []
    with _tcp_server(_counting_handler(attempts)) as url:
        client = http.HttpClient(fetch=http.default_fetch, retries=1, sleep=lambda s: None, timeout=2.0)
        with pytest.raises(http.HttpError):
            client.get(url)
    assert len(attempts) == 2
