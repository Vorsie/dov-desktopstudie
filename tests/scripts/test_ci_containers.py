"""De containerhelper en de workflow moeten hetzelfde draaien.

`scripts/ci_containers.sh` bestaat om CI lokaal na te doen. Draait hij iets anders dan
`ci-qgis.yml`, dan bewijst een groene lokale run niets en is de helper erger dan geen helper.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = (ROOT / ".github" / "workflows" / "ci-qgis.yml").read_text(encoding="utf-8")
SCRIPT = (ROOT / "scripts" / "ci_containers.sh").read_text(encoding="utf-8")


def test_the_helper_runs_every_image_the_workflow_runs():
    """Beide images, en geen andere: 3.34 is de ondergrens die de plugin claimt en `latest` is
    waar een 4.x-breuk het eerst zichtbaar wordt."""
    matrix = set(re.findall(r"(qgis/qgis:[\w.-]+)", WORKFLOW.split("headless-live")[0]))
    # The IMAGES line, not the whole file: the usage comment names an image too, and a helper
    # that had quietly dropped one would still look right to a search over the comments.
    assigned = re.search(r'^IMAGES="([^"]*)"', SCRIPT, re.M)
    assert assigned, SCRIPT[:200]
    helper = set(assigned.group(1).split())

    assert matrix, WORKFLOW[:200]
    assert helper == matrix, f"workflow {sorted(matrix)} tegen helper {sorted(helper)}"


def test_the_helper_selects_the_same_tests():
    """Dezelfde map, dezelfde marker en dezelfde deselectie. Draait de helper de live test wel,
    dan duurt "even lokaal nakijken" een kwartier tegen de echte DOV-diensten."""
    for argument in ('tests/qgis', '-m "not live"',
                     "--deselect tests/qgis/test_pipeline.py::test_live_pipeline_for_gent"):
        assert argument in " ".join(WORKFLOW.split()), argument
        assert argument in " ".join(SCRIPT.split()), argument


def test_the_helper_sets_the_font_directory():
    """Zonder QT_QPA_FONTDIR tekent offscreen elke letter als een zwart blokje terwijl de tests
    groen blijven - dat is precies het soort verschil dat een lokale namaak moet meenemen."""
    for variable in ("QT_QPA_PLATFORM", "QT_QPA_FONTDIR"):
        assert variable in WORKFLOW and variable in SCRIPT, variable
