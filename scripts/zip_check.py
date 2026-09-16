"""Install the plugin from the built zip into a clean QGIS profile and prove it works there: the
zip goes in through the plugin installer of QGIS itself, the plugin is enabled and loaded, the
dialog opens once, and a status file says so before QGIS closes itself.

  "C:\\Program Files\\QGIS 3.40.15\\bin\\qgis-ltr-bin.exe"
      --profile zipcheck --nologo --noversioncheck --code scripts\\zip_check.py

A profile of its own (`--profile zipcheck`), never `default` or `smoke`: the installer writes into
`<profile>/python/plugins` and enables the plugin in that profile's settings, so the script refuses
any profile not named `zipcheck`. The zip is `dist/desktopstudie-<versie>.zip` from
`scripts/build_zip.py`. Under `--code` the script runs before the event loop, so it only schedules
work (QTimer), like `smoke_plugin.py`. The status lands in `uitvoer/zip_check/zip_status.json`
(`installed`, `loaded`, `version`, `dialog_opened`, plus `method` and `plugin_path`), a log next to
it. When `installFromZipFile` is missing or throws, the zip is unpacked into the profile's plugin
folder by hand and `method` says "unzip" instead of "installFromZipFile".

Two things QGIS does that this script has to undo. `sys.argv` is `['']` under `--code`; the real
command line is `QgsApplication.arguments()`, and that is where the checkout is read from. And the
working directory is on `sys.path`, so a QGIS started from the checkout would import the checkout's
package instead of the installed one: any `sys.path` entry that holds the package and is not the
profile's plugin folder is removed before the install, and `removed_from_sys_path` lists them.
`plugin_path` in the status is the proof: it must lie under the profile.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import time
import traceback
import zipfile
from pathlib import Path

from qgis import utils as qgis_utils
from qgis.core import QgsApplication, QgsProject, QgsSettings
from qgis.PyQt.QtCore import QTimer

PLUGIN = "desktopstudie"
PROFILE = "zipcheck"
START_DELAY_MS = 500
QUIT_DELAY_MS = 1500


def _root() -> Path:
    """The checkout: `__file__` is not set under --code, but the path is on the command line.
    QGIS keeps its own arguments (`QgsApplication.arguments()`) and hands Python a bare
    `sys.argv`, so the command line is read from the application, `sys.argv` as a fallback."""
    for argv in (list(QgsApplication.arguments()), sys.argv):
        if "--code" in argv:
            return Path(argv[argv.index("--code") + 1]).resolve().parents[1]
    return Path.cwd()


def home_plugins_dir() -> Path:
    """Where QGIS installs a user's plugins: `<profile>/python/plugins`, the folder the plugin
    installer writes into (its `HOME_PLUGIN_PATH`, a name that has moved between versions)."""
    return Path(QgsApplication.qgisSettingsDirPath()) / "python" / "plugins"


ROOT = _root()
OUT = ROOT / "uitvoer" / "zip_check"
STATUS = OUT / "zip_status.json"
LOG = OUT / "zip_log.txt"
T0 = time.monotonic()
status = {"ok": False, "installed": False, "loaded": False, "version": None, "dialog_opened": False,
          "method": None, "plugin_path": None, "profile": None, "zip": None, "root": str(ROOT),
          "argv": list(QgsApplication.arguments()), "sys_argv": list(sys.argv)}


def note(message: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    line = f"{time.monotonic() - T0:7.1f} s  {message}"
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
    print(line)


def write_status(**fields) -> None:
    status.update(fields)
    status["seconds"] = round(time.monotonic() - T0, 1)
    OUT.mkdir(parents=True, exist_ok=True)
    STATUS.write_text(json.dumps(status, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def quit_qgis() -> None:
    QgsProject.instance().setDirty(False)  # no "save project?" prompt on the way out
    QTimer.singleShot(QUIT_DELAY_MS, qgis_utils.iface.mainWindow().close)


def finish(ok: bool, error: str = None) -> None:
    write_status(ok=ok, error=error)
    note("KLAAR" if ok else f"MISLUKT: {error}")
    quit_qgis()


def zip_file() -> Path:
    """The zip `build_zip.py` writes: the one place that knows its name and version. Loaded from
    its file, not through `sys.path`: the checkout on `sys.path` would shadow the profile's copy
    of the plugin, and then this check proves nothing about the zip."""
    spec = importlib.util.spec_from_file_location("build_zip", ROOT / "scripts" / "build_zip.py")
    build_zip = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build_zip)
    path = build_zip.DIST / f"{build_zip.PACKAGE.name}-{build_zip.version()}.zip"
    if not path.is_file():
        raise FileNotFoundError(f"zip niet gevonden: {path} (draai eerst scripts/build_zip.py)")
    return path


def install(path: Path) -> str:
    """The zip into the profile's plugin folder; returns how it got there."""
    plugins_dir = home_plugins_dir()
    try:
        from pyplugin_installer import instance

        instance().installFromZipFile(str(path))
        method = "installFromZipFile"
    except Exception as exc:  # noqa: BLE001 - the fallback is the point of catching here
        note(f"installFromZipFile niet bruikbaar ({type(exc).__name__}: {exc}); zip wordt uitgepakt")
        with zipfile.ZipFile(path) as archive:
            archive.extractall(plugins_dir)
        qgis_utils.updateAvailablePlugins()
        method = "unzip"
    if not (plugins_dir / PLUGIN / "metadata.txt").is_file():
        raise RuntimeError(f"na installatie geen {PLUGIN}/metadata.txt in {plugins_dir}")
    return method


def load() -> None:
    """Enabled and started in this profile, whichever state the installer left it in."""
    if PLUGIN not in qgis_utils.active_plugins:
        if PLUGIN not in qgis_utils.available_plugins:
            qgis_utils.updateAvailablePlugins()
        if not qgis_utils.loadPlugin(PLUGIN):
            raise RuntimeError("loadPlugin mislukt (zie het logpaneel)")
        if not qgis_utils.startPlugin(PLUGIN):
            raise RuntimeError("startPlugin mislukt (zie het logpaneel)")
    QgsSettings().setValue(f"PythonPlugins/{PLUGIN}", True)


def run() -> None:
    try:
        profile_dir = Path(QgsApplication.qgisSettingsDirPath())
        status["profile"] = str(profile_dir)
        if profile_dir.name != PROFILE:
            raise RuntimeError(f"niet in profiel {PROFILE!r} maar in {profile_dir}; hier wordt niets geïnstalleerd")
        path = zip_file()
        status["zip"] = str(path)
        note(f"zip: {path}")
        # Only the profile's copy may answer to the plugin's name. QGIS puts its working directory
        # on sys.path and the documented command runs from the checkout, so the checkout (or any
        # other folder holding the package) is taken off sys.path here and logged; a package that
        # was imported before this script ran cannot be undone, so that one is refused.
        if PLUGIN in sys.modules:
            raise RuntimeError(f"{PLUGIN} was al geïmporteerd vóór de installatie; de proef zou niets bewijzen")
        shadowing = [entry for entry in sys.path if (Path(entry or ".") / PLUGIN / "metadata.txt").is_file()
                     and Path(entry or ".").resolve() != home_plugins_dir().resolve()]
        for entry in shadowing:
            sys.path.remove(entry)
        status["removed_from_sys_path"] = shadowing
        if shadowing:
            note(f"van sys.path gehaald, zou het profiel overschaduwen: {shadowing}")
        status["method"] = install(path)
        status["installed"] = True
        note(f"geïnstalleerd via {status['method']}")
        load()
        plugin_path = Path(sys.modules[PLUGIN].__file__).resolve().parent
        status["plugin_path"] = str(plugin_path)
        status["loaded"] = PLUGIN in qgis_utils.active_plugins
        status["version"] = qgis_utils.pluginMetadata(PLUGIN, "version")
        note(f"geladen: {status['loaded']}, versie {status['version']}, uit {plugin_path}")
        plugin = qgis_utils.plugins[PLUGIN]
        plugin.run()
        dialog = plugin.dialog
        status["dialog_opened"] = dialog is not None and dialog.isVisible()
        note(f"dialoog open: {status['dialog_opened']}")
        if dialog is not None:
            dialog.close()
        # Loaded from the profile the installer wrote into, not from a junction or the checkout.
        in_profile = home_plugins_dir().resolve() in plugin_path.parents
        ok = all((status["installed"], status["loaded"], status["dialog_opened"], in_profile,
                  status["version"] is not None))
        finish(ok, None if in_profile else f"plugin geladen van buiten het profiel: {plugin_path}")
    except Exception:  # noqa: BLE001 - the status file is the only channel out
        finish(False, traceback.format_exc())


try:
    note(f"zipcheck start in {ROOT}")
    if STATUS.exists():
        STATUS.unlink()
    QTimer.singleShot(START_DELAY_MS, run)
except Exception:  # noqa: BLE001 - the status file is the only channel out
    finish(False, traceback.format_exc())
