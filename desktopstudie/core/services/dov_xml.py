"""Parsers for DOV XML documents (default namespace http://kern.schemas.dov.vlaanderen.be,
matched with the {*} wildcard). Units as delivered by DOV: qc in MPa, fs/u in kPa; Qt (totale
weerstand) is in kN and is not parsed."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Tuple

from ..logging_util import Log
from ..model import CptProfile, GwLevel, LithologyLayer

_DEPTH_TAGS = ("diepte", "lengte", "sondeerdiepte")


def _root(xml_bytes: bytes) -> ET.Element:
    """Parses the document, but refuses one that declares a DTD in its first 1024 bytes: DOV never
    ships a DTD, so its presence signals a hostile document (entity expansion, external entities)."""
    head = xml_bytes.lstrip()[:1024]
    if b"<!DOCTYPE" in head:
        raise ValueError("DOV-XML met DTD geweigerd")
    return ET.fromstring(xml_bytes)


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
    value = value.lstrip(">").strip()  # off-scale marker allowed by the DOV schema pattern
    try:
        return float(value.replace(",", "."))
    except ValueError:
        return None


def _bool(el: Optional[ET.Element], tag: str) -> bool:
    return (_text(el, tag) or "").strip().lower() == "true"


def parse_cpt_profile(xml_bytes: bytes, log: Optional[Log] = None) -> CptProfile:
    root = _root(xml_bytes)
    rows = root.findall(".//{*}meetdata")
    tag = next((t for t in _DEPTH_TAGS if any(_float(row, t) is not None for row in rows)), None)
    depth: List[float] = []
    qc: List[Optional[float]] = []
    fs: List[Optional[float]] = []
    u: List[Optional[float]] = []
    if tag is not None:
        for row in rows:
            d = _float(row, tag)
            if d is None:
                continue
            depth.append(d)
            qc.append(_float(row, "qc"))
            fs.append(_float(row, "fs"))
            u.append(_float(row, "u"))
    if rows and not depth:
        if log:
            log.warning(f"{len(rows)} meetdata-rijen zonder bruikbare diepte - leeg profiel")
    elif depth:
        if log:
            log.debug(f"{len(depth)} meetpunten (diepte uit '{tag}')")
        if len(depth) < len(rows) and log:
            log.warning(f"{len(rows) - len(depth)} van {len(rows)} meetdata-rijen zonder '{tag}' overgeslagen")
    return CptProfile(depth_m=depth, qc_mpa=qc, fs_kpa=fs, u_kpa=u)


def _describe(laag: ET.Element) -> Tuple[str, Dict[str, Any]]:
    return _text(laag, "beschrijving") or "", {}


def _coded_description(laag: ET.Element) -> Tuple[str, Dict[str, Any]]:
    main = laag.find("{*}hoofdnaam")
    hoofdnaam = _text(main, "grondsoort") or "?"
    kleur = _text(laag, "kleur")
    admixtures: List[Dict[str, Any]] = []
    admix_desc: List[str] = []
    for b in laag.findall("{*}bijmenging"):
        code = _text(b, "grondsoort")
        amount = _text(b, "hoeveelheid")
        local = _bool(b, "plaatselijk")
        if code is None:
            continue
        admixtures.append({"grondsoort": code, "hoeveelheid": amount, "plaatselijk": local})
        token = f"{code}{'/' + amount if amount else ''}"
        admix_desc.append(f"plaatselijk {token}" if local else token)
    parts = [hoofdnaam]
    if kleur:
        parts.append(f"({kleur})")
    if admix_desc:
        parts.append("bijmenging: " + ", ".join(admix_desc))
    raw: Dict[str, Any] = {"hoofdnaam": hoofdnaam}
    if kleur:
        raw["kleur"] = kleur
    if admixtures:
        raw["bijmenging"] = admixtures
    return " ".join(parts), raw


# (container tag, LithologyLayer.kind, per-<laag> extractor returning (description, raw)) -- tried
# in order, first variant present in the document wins.
_LITHOLOGY_VARIANTS = (
    ("lithologischebeschrijving", "beschrijving", _describe),
    ("gecodeerdelithologie", "gecodeerd", _coded_description),
)


def parse_lithology(xml_bytes: bytes, log: Optional[Log] = None) -> List[LithologyLayer]:
    root = _root(xml_bytes)
    layers: List[LithologyLayer] = []
    for tag, kind, extract in _LITHOLOGY_VARIANTS:
        container = root.find(f".//{{*}}{tag}")
        if container is None:
            continue
        for laag in container.findall("{*}laag"):
            top, base = _float(laag, "van"), _float(laag, "tot")
            if top is None or base is None:
                continue
            description, raw = extract(laag)
            layers.append(LithologyLayer(top, base, description, kind, raw))
        break
    else:
        if log:
            log.warning("geen lithologische beschrijving of gecodeerde lithologie in interpretatie")
    return layers


def parse_groundwater_levels(xml_bytes: bytes, log: Optional[Log] = None) -> List[GwLevel]:
    root = _root(xml_bytes)
    rows = root.findall(".//{*}peilmeting")
    levels: List[GwLevel] = []
    for pm in rows:
        date, level = _text(pm, "datum"), _float(pm, "peil_mtaw")
        if date is None or level is None:
            continue
        levels.append(GwLevel(date=date, level_mtaw=level, method=_text(pm, "methode"),
                              reliability=_text(pm, "betrouwbaarheid")))
    levels.sort(key=lambda lv: lv.date)
    if rows and not levels and log:
        log.warning(f"{len(rows)} peilmetingen zonder bruikbare datum/peil - geen waterstanden")
    return levels
