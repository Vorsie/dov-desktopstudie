"""Shared test helpers. FixtureClient mimics HttpClient (get/get_json/get_text) and serves
recorded files by URL-substring routes, recording every requested URL."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def fixture_json(name: str):
    return json.loads(fixture_bytes(name).decode("utf-8"))


class FixtureClient:
    def __init__(self, routes=None):
        # routes: list of (substring, fixture filename or bytes or Exception instance)
        self.routes = list(routes or [])
        self.calls: list[str] = []

    def route(self, substring: str, target) -> FixtureClient:
        self.routes.append((substring, target))
        return self

    def get(self, url: str, params=None) -> bytes:
        from desktopstudie.core.services.http import build_url

        full = build_url(url, params)
        self.calls.append(full)
        for substring, target in self.routes:
            if substring in full:
                if isinstance(target, Exception):
                    raise target
                if isinstance(target, bytes):
                    return target
                return fixture_bytes(target)
        raise AssertionError(f"no fixture route for {full}")

    def get_text(self, url: str, params=None) -> str:
        return self.get(url, params).decode("utf-8")

    def get_json(self, url: str, params=None):
        return json.loads(self.get_text(url, params))


@pytest.fixture
def gent_ring():
    return [(104226.0, 192406.0), (104426.0, 192406.0), (104426.0, 192606.0), (104226.0, 192606.0)]
