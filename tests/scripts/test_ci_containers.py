"""De containerhelper en de workflow moeten hetzelfde draaien - en niet vaker dan nodig.

`scripts/ci_containers.sh` bestaat om CI lokaal na te doen. Draait hij iets anders dan
`ci-qgis.yml`, dan bewijst een groene lokale run niets en is de helper erger dan geen helper.

En wanneer CI draait is hier ook een regel: de minuten van een account zijn eindig, en de twee
workflows hebben ze een tijd lang twee keer per commit opgemaakt.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
WORKFLOW = (WORKFLOWS / "ci-qgis.yml").read_text(encoding="utf-8")
SCRIPT = (ROOT / "scripts" / "ci_containers.sh").read_text(encoding="utf-8")


def _triggers(text: str) -> str:
    """Wat er achter `on:` staat: de rest van de regel, of alles eronder tot de eerste regel die
    weer helemaal links begint. Dus de triggers en niets anders - een woord in het commentaarblok
    erboven telt niet mee. Beide vormen, want `on: [push, pull_request]` is precies de vorm die
    hier niet terug mag komen en die moet een leesbare melding geven, geen AttributeError."""
    found = re.search(r"^on:(?:.+|\n(?:[ \t#].*\n|\n)*)", text, re.M)
    assert found, text[:200]
    return found.group(0)


def test_the_helper_runs_every_image_the_workflow_runs():
    """Beide images, en geen andere: 3.34 is de ondergrens die de plugin claimt en `latest` is
    waar een 4.x-breuk het eerst zichtbaar wordt."""
    # De matrixregel zelf, niet alles boven een jobnaam: die naam staat ook in het commentaar,
    # en dan leest een split hem daar en vindt deze zoeker geen enkel image meer.
    listed = re.search(r"^\s*image:\s*\[([^\]]*)\]", WORKFLOW, re.M)
    assert listed, WORKFLOW[:200]
    matrix = set(re.findall(r"qgis/qgis:[\w.-]+", listed.group(1)))
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


def test_geen_enkele_workflow_draait_dezelfde_commit_twee_keer():
    """Een workflow die op `push` en op `pull_request` staat zonder de push te beperken, draait
    elke commit op een branch met een openstaande pull request twee keer - dezelfde commit,
    dezelfde uitkomst, dubbele minuten. Push hoort dus bij de branches die geen pull request van
    zichzelf hebben."""
    for path in sorted(WORKFLOWS.glob("*.yml")):
        triggers = _triggers(path.read_text(encoding="utf-8"))
        if "push" in triggers and "pull_request" in triggers:
            assert re.search(r"^\s+branches: \[", triggers, re.M), f"{path.name}: {triggers.strip()}"


def test_de_live_studie_draait_wekelijks_en_niet_op_elke_commit():
    """Een volledige studie tegen de echte diensten is duur, mag falen omdat DOV plat ligt en is
    geen verplichte check. Die hoort op een schema en op een knop, niet op elke commit."""
    triggers = _triggers(WORKFLOW)
    assert "schedule" in triggers and "workflow_dispatch" in triggers, triggers
    job = WORKFLOW.split("headless-live:")[1]
    assert "if: github.event_name == 'schedule' || github.event_name == 'workflow_dispatch'" in job
