"""The one version the project declares, read from pyproject.toml.

Read with a regex rather than tomllib: the core tests also run on Python 3.9, which has none, and a
literal "0.1.0" in three test files is three places that forget a release.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def pyproject_version() -> str:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version = "([^"]+)"$', text, re.MULTILINE)
    assert match, "pyproject.toml declares no version"
    return match.group(1)
