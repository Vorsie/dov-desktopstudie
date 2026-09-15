"""Relief of the study zone from the DHMV II DTM (WCS): min / max / mean in mTAW.

The core leaves `StudyResult.relief` empty; only the shell has a raster engine to sample the
terrain with. Every failure here returns None with a WARNING rather than a fabricated 0.0: a flat
zone and an unreachable service must never read the same in the report.
"""
from __future__ import annotations

from typing import Callable, Optional, Tuple

from qgis.analysis import QgsZonalStatistics
from qgis.core import QgsFeedback, QgsVectorLayer

from ..core.catalogue import DHMV_WCS_COVERAGE, DHMV_WCS_URL
from . import layers

DTM_NAME = "DHMV II DTM 1 m"
PREFIX = "dhmv_"
BAND = 1
# Both enums moved to Qgis (Qgis.ZonalStatistic / Qgis.ZonalStatisticResult) in QGIS 3.36;
# QgsZonalStatistics keeps `Statistic` and `Result` as deprecated aliases, and on 3.34 those are
# the only spellings (unscoped C++ enums, so sip exposes both `QgsZonalStatistics.Statistic.Min`
# and `QgsZonalStatistics.Min` there). Resolving the enum holder once lands on the member under
# every one of those spellings, on 3.34 through 4.x.
_STAT = getattr(QgsZonalStatistics, "Statistic", QgsZonalStatistics)
_RESULT = getattr(QgsZonalStatistics, "Result", QgsZonalStatistics)
STATISTICS = _STAT.Min | _STAT.Max | _STAT.Mean
SUCCESS = _RESULT.Success


def _result_name(code) -> str:
    """The result code by the name QGIS gives it. A bare "3" in a log line tells nobody what went
    wrong; "LayerTypeWrong" says the zone was not a polygon layer."""
    name = getattr(code, "name", None)
    if name:
        return str(name)
    for candidate in dir(_RESULT):
        if not candidate.startswith("_") and getattr(_RESULT, candidate, None) == code:
            return candidate
    return str(code)


class _CancelFeedback(QgsFeedback):
    """A feedback that asks the caller whether the run should stop.

    `QgsFeedback.isCanceled()` is NOT virtual (3.34 and 3.40 both declare it inline), so
    overriding it in Python is invisible to the C++ loop that polls it. What is observable is
    `cancel()`: QgsZonalStatistics reports progress per feature and checks `isCanceled()` right
    around it, so a slot on `progressChanged` that calls `cancel()` lands exactly between the two.
    """

    def __init__(self, should_cancel: Callable[[], bool]):
        super().__init__()
        self._should_cancel = should_cancel
        self.progressChanged.connect(self._poll)
        self._poll()

    def _poll(self, *_progress) -> None:
        if not self.isCanceled() and self._should_cancel():
            self.cancel()


def relief_of_zone(zone_layer: QgsVectorLayer, log=None,
                   should_cancel: Optional[Callable[[], bool]] = None
                   ) -> Optional[Tuple[float, float, float]]:
    """(min, max, mean) height in mTAW over the zone polygon, or None when the DTM is unusable.

    The caller's layer comes back exactly as it went in. QgsZonalStatistics writes its three
    columns onto the polygon layer it samples, and that same layer goes into the GeoPackage and
    onto every map page - so the sampling happens on a clone and only the numbers come back.

    `should_cancel` is polled while the raster is being read; a cancelled run yields None, never
    a half-measured zone.
    """
    dtm = layers.wcs_layer(DHMV_WCS_URL, DHMV_WCS_COVERAGE, DTM_NAME)
    if not dtm.isValid():
        if log:
            log.warning(f"DHMV WCS niet beschikbaar ({DHMV_WCS_URL}); geen relief")
        return None
    sample = zone_layer.clone()
    feedback = _CancelFeedback(should_cancel) if should_cancel is not None else None
    code = QgsZonalStatistics(sample, dtm, PREFIX, BAND, STATISTICS).calculateStatistics(feedback)
    if code != SUCCESS:
        if log:
            log.warning(f"DHMV zonale statistiek gaf {_result_name(code)}; geen relief")
        return None
    feature = next(sample.getFeatures(), None)
    if feature is None:
        if log:
            log.warning("Zonelaag zonder object; geen relief")
        return None
    try:
        lo = float(feature[PREFIX + "min"])
        hi = float(feature[PREFIX + "max"])
        mean = float(feature[PREFIX + "mean"])
    except (KeyError, TypeError, ValueError):
        # Success with empty attributes: the zone holds no raster cell at all. The DTM stops at
        # the region border, and a zone over open water has nothing to measure either.
        if log:
            log.warning("DHMV zonale statistiek leverde geen waarden; ligt de zone binnen het DTM?")
        return None
    if log:
        log.info(f"Relief uit {DTM_NAME}: min {lo:.2f} / gemiddeld {mean:.2f} / max {hi:.2f} mTAW")
    return lo, hi, mean
