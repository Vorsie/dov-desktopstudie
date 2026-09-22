"""What the plugin remembers between sessions: the title-page fields that do not change from one
study to the next, and the few choices a user makes once.

Stored under `desktopstudie/` in QgsSettings - the user's QGIS profile - with the Dutch key names
from the plan, so they sit together in the advanced settings of QGIS. Every read falls back to its
default when the stored value cannot be read: a hand-edited profile must not take the dialog down.
The store is injectable so the tests write to an ini file of their own instead of the profile.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Optional

from qgis.core import QgsSettings

from ..core.services.http import CACHE_MODES

PREFIX = "desktopstudie"
DEFAULT_RADIUS_M = 500.0
DEFAULT_CACHE_MODE = "use"
# The separate legend pages are OFF unless the user asks for them: every map with a legend turns
# into one or more sheets that nobody asked for, while the classes that actually lie in the zone
# stand under their own map. The compact layout is off for the opposite reason - the default
# report has to come out the same shape every time.
DEFAULT_LEGENDS = False
DEFAULT_COMPACT = False
TRUE_WORDS = ("true", "1", "ja", "yes")


def default_output_dir() -> str:
    """Under the user's documents, computed when asked: the home directory is the user's, not the
    machine's, and a default frozen at import time would follow whoever imported first."""
    return str(Path.home() / "Documents" / "Desktopstudies")


def _text(value: Any, default: str) -> str:
    return default if value is None else str(value)


def _number(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _flag(value: Any, default: bool) -> bool:
    """QSettings hands a bool back as a bool in the session that wrote it and as the text "true" or
    "false" after a restart; both read the same here."""
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in TRUE_WORDS


def _mode(value: Any, default: str) -> str:
    return value if value in CACHE_MODES else default


class _Field:
    """One setting: its key under the prefix, its default and how to read what the store holds."""

    def __init__(self, key: str, default: Any, read: Callable[[Any, Any], Any]):
        self.key, self.default, self.read = key, default, read

    def __get__(self, settings: Optional[PluginSettings], owner=None):
        if settings is None:  # read off the class: the field itself, for whoever lists the keys
            return self
        default = self.default() if callable(self.default) else self.default
        return self.read(settings.store.value(f"{PREFIX}/{self.key}", None), default)

    def __set__(self, settings: PluginSettings, value: Any) -> None:
        settings.store.setValue(f"{PREFIX}/{self.key}", value)


class PluginSettings:
    """The plugin's settings, read from and written to `store` (QgsSettings by default)."""

    company = _Field("bedrijf", "", _text)
    author = _Field("auteur", "", _text)
    logo = _Field("logo", "", _text)
    radius_m = _Field("straal", DEFAULT_RADIUS_M, _number)
    output_dir = _Field("uitvoermap", default_output_dir, _text)
    cache_mode = _Field("cache", DEFAULT_CACHE_MODE, _mode)
    legends = _Field("legendas", DEFAULT_LEGENDS, _flag)
    compact = _Field("compact", DEFAULT_COMPACT, _flag)

    def __init__(self, store: Optional[Any] = None):
        self.store = store if store is not None else QgsSettings()

    def sync(self) -> None:
        """Write through to disk now; QSettings otherwise flushes when it sees fit."""
        self.store.sync()
