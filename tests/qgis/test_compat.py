"""De schil draait op QGIS 3.34 t/m 4.x: layout-maten worden altijd in millimeter gemaakt
en de versie is herkenbaar als 3.x of 4.x."""
from __future__ import annotations


def test_point_mm_is_in_millimetres(qgs_app):
    from desktopstudie.qgis import compat

    p = compat.point_mm(10, 20)
    assert (p.x(), p.y()) == (10, 20)
    assert p.units() == compat.MM


def test_size_mm_is_in_millimetres(qgs_app):
    from desktopstudie.qgis import compat

    s = compat.size_mm(180, 200)
    assert (s.width(), s.height()) == (180, 200)
    assert s.units() == compat.MM


def test_version_is_three_or_four(qgs_app):
    from desktopstudie.qgis import compat

    assert compat.qgis_version().startswith(("3.", "4."))
