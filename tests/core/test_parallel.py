"""Een reeks items parallel ophalen, elk geïsoleerd: één bron die plat ligt kost dat item, niet
de hele fase."""
from __future__ import annotations

import threading

import pytest

from desktopstudie.core import parallel
from desktopstudie.core.logging_util import Log


def _log(lines):
    return Log("parallel", lines.append)


def test_one_failing_item_costs_that_item_and_not_the_batch():
    """`pool.map` gooit de eerste fout bij het itereren en verliest de rest; hier hoort elk item
    zijn eigen lot te hebben: twee geladen, één mislukt, en het aantal mislukkingen terug."""
    loaded = []

    def load_one(item):
        if item == "stuk":
            raise RuntimeError("502")
        loaded.append(item)

    failed = parallel.load_each(["een", "stuk", "twee"], load_one, "fiche")

    assert failed == 1
    assert sorted(loaded) == ["een", "twee"]


def test_what_was_not_loaded_is_logged_with_its_label():
    """Log wat NIET gelukt is: "0 opgehaald" zonder reden is geen diagnose."""
    lines = []

    parallel.load_each(["stuk"], lambda item: 1 / 0, "peilmeting", log=_log(lines))

    warnings = [line for line in lines if "WARNING" in line]
    assert warnings and "peilmeting" in warnings[0], lines
    assert "ZeroDivisionError" in warnings[0], warnings


def test_every_item_is_tried_even_when_the_first_one_fails():
    """De volgorde waarin de threads klaar zijn, mag het resultaat niet bepalen."""
    seen = []
    lock = threading.Lock()

    def load_one(item):
        with lock:
            seen.append(item)
        if item % 2 == 0:
            raise RuntimeError("even valt om")

    failed = parallel.load_each(list(range(10)), load_one, "item", max_workers=4)

    assert sorted(seen) == list(range(10))
    assert failed == 5


def test_a_cancelled_batch_stops_instead_of_finishing_the_queue():
    """Afbreken hoort te stoppen: de oproeper wacht niet tot alle honderd fiches binnen zijn."""
    loaded = []

    def load_one(item):
        loaded.append(item)

    with pytest.raises(parallel.Cancelled):
        parallel.load_each(list(range(100)), load_one, "item", max_workers=1,
                           should_cancel=lambda: len(loaded) >= 1)

    assert len(loaded) < 100


def test_nothing_to_load_is_no_work_and_no_failures():
    assert parallel.load_each([], lambda item: None, "item") == 0
