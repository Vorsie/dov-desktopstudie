"""Parsers for DOV XML documents (default namespace http://kern.schemas.dov.vlaanderen.be,
matched with the {*} wildcard). Units as delivered by DOV: qc/Qt in MPa, fs/u in kPa."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import List, Optional

from ..model import CptProfile, GwLevel, LithologyLayer


def _text(el: Optional[ET.Element], tag: str) -> Optional[str]:
    if el is None:
        return None
    child = el.find(f"{{*}}{tag}")
    if child is None or child.text is None:
        return None
    return child.text.strip()


def _float(el: Optional[ET.Element], tag: str) -> Optional[float]:
    value = _text(el, tag)
    if value in (None, ""):
        return None
    try:
        return float(value.replace(",", "."))
    except ValueError:
        return None


def parse_cpt_profile(xml_bytes: bytes) -> CptProfile:
    root = ET.fromstring(xml_bytes)
    depth: List[float] = []
    qc: List[Optional[float]] = []
    fs: List[Optional[float]] = []
    u: List[Optional[float]] = []
    for row in root.findall(".//{*}meetdata"):
        d = _float(row, "diepte")
        if d is None:
            d = _float(row, "lengte")
        if d is None:
            continue
        depth.append(d)
        qc.append(_float(row, "qc"))
        fs.append(_float(row, "fs"))
        u.append(_float(row, "u"))
    return CptProfile(depth_m=depth, qc_mpa=qc, fs_kpa=fs, u_kpa=u)


def _coded_description(laag: ET.Element) -> str:
    main = laag.find("{*}hoofdnaam")
    parts = [_text(main, "grondsoort") or "?"]
    colour = _text(laag, "kleur")
    if colour:
        parts.append(f"({colour})")
    admix = []
    for b in laag.findall("{*}bijmenging"):
        code = _text(b, "grondsoort")
        amount = _text(b, "hoeveelheid")
        if code:
            admix.append(f"{code}{'/' + amount if amount else ''}")
    if admix:
        parts.append("bijmenging: " + ", ".join(admix))
    return " ".join(parts)


def parse_lithology(xml_bytes: bytes) -> List[LithologyLayer]:
    root = ET.fromstring(xml_bytes)
    layers: List[LithologyLayer] = []
    described = root.find(".//{*}lithologischebeschrijving")
    coded = root.find(".//{*}gecodeerdelithologie")
    if described is not None:
        for laag in described.findall("{*}laag"):
            top, base = _float(laag, "van"), _float(laag, "tot")
            if top is None or base is None:
                continue
            layers.append(LithologyLayer(top, base, _text(laag, "beschrijving") or "", "beschrijving"))
    elif coded is not None:
        for laag in coded.findall("{*}laag"):
            top, base = _float(laag, "van"), _float(laag, "tot")
            if top is None or base is None:
                continue
            layers.append(LithologyLayer(top, base, _coded_description(laag), "gecodeerd"))
    return layers


def parse_groundwater_levels(xml_bytes: bytes) -> List[GwLevel]:
    root = ET.fromstring(xml_bytes)
    levels: List[GwLevel] = []
    for pm in root.findall(".//{*}peilmeting"):
        date, level = _text(pm, "datum"), _float(pm, "peil_mtaw")
        if date is None or level is None:
            continue
        levels.append(GwLevel(date=date, level_mtaw=level, method=_text(pm, "methode"),
                              reliability=_text(pm, "betrouwbaarheid")))
    levels.sort(key=lambda lv: lv.date)
    return levels
