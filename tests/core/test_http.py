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


def test_cache_mode_off_does_not_create_the_cache_directory(tmp_path):
    def fetch(url, timeout, user_agent):
        return b'{"a": 1}'

    cache = tmp_path / "cache"
    client = http.HttpClient(cache_dir=cache, fetch=fetch, cache_mode="off")
    client.get_json("https://x.be/a")
    assert not cache.exists()  # caching off means no trace on disk at all


def test_a_single_call_may_shorten_the_timeout_and_the_retries():
    """Een fiche is één item van honderd: daar hoort een korte adem bij, terwijl de WFS-oproep die
    de hele tabel levert de volle tijd krijgt. Beide uit dezelfde client, dus per oproep."""
    seen = []

    def fetch(url, timeout, user_agent):
        seen.append(timeout)
        raise http.HttpError(url, 503, "busy")

    client = http.HttpClient(fetch=fetch, timeout=60.0, retries=2, sleep=lambda s: None)

    with pytest.raises(http.HttpError):
        client.get("https://x.be/fiche.xml", timeout=15.0, retries=1)

    assert seen == [15.0, 15.0]  # één poging plus één herkansing, allebei met de korte timeout


def test_without_overrides_a_call_keeps_the_clients_own_settings():
    seen = []

    def fetch(url, timeout, user_agent):
        seen.append(timeout)
        return b"ok"

    client = http.HttpClient(fetch=fetch, timeout=42.0, retries=2, sleep=lambda s: None)

    assert client.get("https://x.be/a") == b"ok"
    assert seen == [42.0]


DOORPRIK_URL = ("https://services.dov.vlaanderen.be/virtueleboringserver/base/virtueleprofielen/"
                "doorprik/g3dv3_F")
WATERINFO_URL = ("https://inspirepub.waterinfo.be/arcgis/services/informatieplicht/"
                 "overstromingsgevoelige_gebieden_pluviaal/MapServer/WMSServer")


def test_a_path_too_long_for_a_table_column_keeps_its_host_and_its_last_segment():
    """De bronnentabel kapt af wat niet in haar kolom past, en een URL heeft geen spaties om op te
    breken: de watertoets-URL van 125 tekens eindigt op het blad als "...overstromingsgev" - midden
    in een woord, en dus onbruikbaar. Een WFS-URL past wel en blijft zoals ze is; een pad dat niet
    past, wordt teruggebracht tot de dienst en het laatste stuk, want dat is wat de lezer nog kan
    thuisbrengen."""
    assert http.short_url(DOORPRIK_URL) == "https://services.dov.vlaanderen.be/.../g3dv3_F"
    assert http.short_url(WATERINFO_URL) == "https://inspirepub.waterinfo.be/.../WMSServer"
    assert http.short_url("https://www.dov.vlaanderen.be/geoserver/wfs") == \
        "https://www.dov.vlaanderen.be/geoserver/wfs"


def test_a_shortened_path_still_names_the_request_it_carried():
    """Het inkorten van het pad mag de dienstnaam niet opeten: de legenda-URL van de watertoets is
    lang EN draagt een REQUEST, en zonder dat achtervoegsel staan er twee identieke regels in de
    bronnentabel."""
    assert http.short_url(WATERINFO_URL + "?SERVICE=WMS&REQUEST=GetLegendGraphic") == \
        "https://inspirepub.waterinfo.be/.../WMSServer (GetLegendGraphic)"


QUARTAIR_DRAWING = ("https://datasets.omgeving.vlaanderen.be/be.vlaanderen.omgeving.distribution.geo."
                    "e58c3358-e149-42b6-9229-c3a9ac88c3d4.DOV_Quartair_50000_22010_png")


def test_one_endless_path_segment_keeps_its_tail():
    """De legenda-URL van een quartairprofieltype is één segment van honderd tekens: er valt geen
    map weg te laten. Wat de lezer eraan heeft staat achteraan - de bestandsnaam met het
    profieltype erin - dus dat stuk blijft staan."""
    short = http.short_url(QUARTAIR_DRAWING)

    assert short.startswith("https://datasets.omgeving.vlaanderen.be/...")
    assert short.endswith("DOV_Quartair_50000_22010_png")
    assert len(short) < len(QUARTAIR_DRAWING) - 30


def test_a_single_call_may_step_past_the_cache(tmp_path):
    """Een dienst die met HTTP 200 haar eigen webpagina teruggeeft in plaats van het bestand, zet
    die pagina in de schijfcache - en dan levert elke volgende run diezelfde pagina. De oproeper
    die dat merkt, moet één keer langs de cache heen kunnen vragen zonder de hele client om te
    zetten."""
    answers = [b"<html>geen bestand</html>", b"\x89PNG\r\n\x1a\nhet echte bestand"]

    def fetch(url, timeout, user_agent):
        return answers.pop(0)

    client = http.HttpClient(cache_dir=tmp_path, fetch=fetch, cache_mode="use")

    assert client.get("https://x.be/tekening.png") == b"<html>geen bestand</html>"
    assert client.get("https://x.be/tekening.png") == b"<html>geen bestand</html>", "uit de cache"
    fresh = client.get("https://x.be/tekening.png", cache_mode="refresh")

    assert fresh.startswith(b"\x89PNG")
    assert client.get("https://x.be/tekening.png").startswith(b"\x89PNG"), "de cache is bijgewerkt"


def test_an_unknown_cache_mode_on_a_call_raises_value_error(tmp_path):
    client = http.HttpClient(cache_dir=tmp_path, fetch=lambda u, t, a: b"x")

    with pytest.raises(ValueError):
        client.get("https://x.be/a", cache_mode="sometimes")
