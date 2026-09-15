"""Relief of the study zone from the DHMV II DTM (WCS): min / max / mean in mTAW.

The core leaves `StudyResult.relief` empty; only the shell has a raster engine to sample the
terrain with. Every failure here returns None with a WARNING rather than a fabricated 0.0: a flat
zone and an unreachable service must never read the same in the report.
"""
from __future__ import annotations

from typing import Optional, Tuple

from qgis.analysis import QgsZonalStatistics
from qgis.core import QgsVectorLayer

from ..core.catalogue import DHMV_WCS_COVERAGE, DHMV_WCS_URL
from . import layers

DTM_NAME = "DHMV II DTM 1 m"
PREFIX = "dhmv_"
BAND = 1
# 3.40 moved this enum to Qgis.ZonalStatistic and keeps QgsZonalStatistics.Statistic as a
# deprecated alias; 3.34 has it only on QgsZonalStatistics, as an unscoped C++ enum (so sip
# exposes both `QgsZonalStatistics.Statistic.Min` and `QgsZonalStatistics.Min` there). Resolving
# the enum holder once lands on the member under every one of those spellings.
_STAT = getattr(QgsZonalStatistics, "Statistic", QgsZonalStatistics)
STATISTICS = _STAT.Min | _STAT.Max | _STAT.Mean


def relief_of_zone(zone_layer: QgsVectorLayer, log=None) -> Optional[Tuple[float, float, float]]:
    """(min, max, mean) height in mTAW over the zone polygon, or None when the DTM is unusable.

    `zone_layer` is sampled in place - QgsZonalStatistics writes three attributes onto it - so
    hand it the memory layer from `layers.zone_layer`, not a layer already in the project tree.
    """
    dtm = layers.wcs_layer(DHMV_WCS_URL, DHMV_WCS_COVERAGE, DTM_NAME)
    if not dtm.isValid():
        if log:
            log.warning(f"DHMV WCS niet beschikbaar ({DHMV_WCS_URL}); geen relief")
        return None
    QgsZonalStatistics(zone_layer, dtm, PREFIX, BAND, STATISTICS).calculateStatistics(None)
    feature = next(zone_layer.getFeatures(), None)
    if feature is None:
        if log:
            log.warning("Zonelaag zonder object; geen relief")
        return None
    try:
        lo = float(feature[PREFIX + "min"])
        hi = float(feature[PREFIX + "max"])
        mean = float(feature[PREFIX + "mean"])
    except (KeyError, TypeError, ValueError):
        # No exception, just NULL attributes, when the zone falls outside the coverage: the DTM
        # stops at the region border, and a zone over water has no cells either.
        if log:
            log.warning("DHMV zonale statistiek leverde geen waarden; ligt de zone binnen het DTM?")
        return None
    if log:
        log.info(f"Relief uit {DTM_NAME}: min {lo:.2f} / gemiddeld {mean:.2f} / max {hi:.2f} mTAW")
    return lo, hi, mean
