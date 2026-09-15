"""Fact-driven signalling rules. Each rule: StudyResult -> list[Signalering]. No judgement,
only facts + source + a fixed attention sentence for the ground investigation."""
from __future__ import annotations

import re
from typing import Callable, List, Optional

from .catalogue import WATERTOETS_LABELS
from .model import Signalering, StudyResult, VirtualBorehole
from .services.virtuele_boring import layers_named

SOFT_WORDS = re.compile(r"\b(klei|veen|leem)\b")
WET_DRAINAGE = {"e", "f", "g", "h", "i"}
SOFT_TEXTURES = {"V", "E", "U"}
BUILT_UP_PREFIXES = ("OB", "ON", "OT", "OE")
# DOV grades landslide susceptibility as klasse "1".."3" with a matching Dutch label - live
# check 2026-09-15 over the Flemish Ardennes: exactly "lage"/"matige"/"hoge gevoeligheid".
# From class 2 ("matige gevoeligheid") upwards the slope is worth investigating. The labels
# are inflected, so match "hoge" as well as the dictionary form "hoog".
LANDSLIDE_MIN_CLASS = 2
LANDSLIDE_WORDS = ("matig", "hoge", "hoog")
SEVERITIES = ("info", "aandacht")

Rule = Callable[[StudyResult], List[Signalering]]


def _vb(result: StudyResult, *models: str) -> Optional[VirtualBorehole]:
    for m in models:
        if m in result.virtual_boreholes and result.virtual_boreholes[m].layers:
            return result.virtual_boreholes[m]
    return None


def _facts(result: StudyResult, map_id: str):
    for mf in result.map_facts:
        if mf.map_id == map_id:
            return mf.rows
    return []


def check_anthropogenic(result: StudyResult) -> List[Signalering]:
    # the "Antropogeen" unit only exists in the formation model; fall back to the member model
    vb = _vb(result, "g3dv3_F", "g3dv3_L")
    if vb is None:
        return []
    matches = layers_named(vb, "antropogeen")
    if not matches:
        return []
    total = sum(layer.thickness_m for layer in matches)
    return [Signalering(
        "antropogeen",
        f"Antropogene laag van {total:.1f} m in de virtuele boring ({vb.model}).",
        "DOV virtuele boring G3Dv3",
        "Aandachtspunt voor het grondonderzoek: ophoging/opvulling met mogelijke obstakels; "
        "dikte en samenstelling ter plaatse vaststellen.")]


def check_soft_layers(result: StudyResult) -> List[Signalering]:
    vb = _vb(result, "g3dv3_L", "g3dv3_F")
    if vb is None:
        return []
    out = []
    for layer in vb.layers:
        top_m, base_m = vb.depth_of(layer)
        if top_m < 10.0 and SOFT_WORDS.search(layer.texture.lower()):
            out.append(Signalering(
                "slappe_laag",
                f"{layer.name} ({layer.texture}) van {top_m:.1f} tot {base_m:.1f} m-mv in de virtuele boring.",
                "DOV virtuele boring G3Dv3",
                "Aandachtspunt voor het grondonderzoek: samendrukbare of cohesieve laag binnen 10 m; "
                "sonderingen tot onder deze laag en monstername overwegen."))
    return out


def check_shallow_tertiary(result: StudyResult) -> List[Signalering]:
    vb = _vb(result, "g3dv3_P")
    if vb is None or vb.surface_mtaw is None:
        return []
    quaternary = layers_named(vb, "quartair")
    if not quaternary:
        return [Signalering(
            "ondiep_tertiair", "Geen Quartair in de virtuele boring: Tertiair aan het maaiveld.",
            "DOV virtuele boring G3Dv3",
            "Aandachtspunt voor het grondonderzoek: Tertiair op geringe diepte; overgang en "
            "eventuele verwering in kaart brengen.")]
    depth = vb.surface_mtaw - min(layer.base_mtaw for layer in quaternary)
    if depth < 3.0:
        return [Signalering(
            "ondiep_tertiair", f"Basis van het Quartair op {depth:.1f} m-mv (virtuele boring).",
            "DOV virtuele boring G3Dv3",
            "Aandachtspunt voor het grondonderzoek: Tertiair op geringe diepte; overgang en "
            "eventuele verwering in kaart brengen.")]
    return []


def check_soil_map(result: StudyResult) -> List[Signalering]:
    out = []
    for row in _facts(result, "bodemkaart"):
        code = str(row.get("Bodemtype") or "")
        drainage = str(row.get("Drainageklasse_code") or "")
        texture = str(row.get("Textuurklasse_code") or "")
        legend = row.get("Gegeneraliseerde_legende")
        if drainage in WET_DRAINAGE:
            out.append(Signalering(
                "bodem_nat", f"Bodemtype {code}: drainageklasse {drainage} (nat).", "DOV bodemkaart",
                "Aandachtspunt voor het grondonderzoek: hoge grondwaterstand mogelijk; peilbuis plaatsen."))
        if texture in SOFT_TEXTURES:
            out.append(Signalering(
                "bodem_veen_klei", f"Bodemtype {code}: textuurklasse {texture}.", "DOV bodemkaart",
                "Aandachtspunt voor het grondonderzoek: veen- of kleibodem; samendrukbaarheid onderzoeken."))
        if code.startswith(BUILT_UP_PREFIXES) or legend == "Antropogeen":
            out.append(Signalering(
                "bodem_antropogeen", f"Bodemtype {code}: antropogeen (bebouwd/vergraven/opgehoogd).",
                "DOV bodemkaart",
                "Aandachtspunt voor het grondonderzoek: verstoorde toplaag; historiek van het terrein nagaan."))
    return out


def check_groundwater(result: StudyResult) -> List[Signalering]:
    candidates = [f for f in result.gw_filters if f.latest_depth_m is not None]
    if not candidates:
        return []
    nearest = min(candidates, key=lambda f: f.distance_m)
    depth = nearest.latest_depth_m
    if depth is not None and depth < 2.0:
        return [Signalering(
            "ondiep_grondwater",
            f"Peilput {nearest.gw_id}: laatste peil {depth:.1f} m-mv op {nearest.latest.date} "
            f"({nearest.distance_m:.0f} m van de zone).",
            "DOV grondwatermeetnet",
            "Aandachtspunt voor het grondonderzoek: ondiepe grondwaterstand; bemaling en "
            "waterspanningen meenemen.")]
    return []


def check_flood(result: StudyResult) -> List[Signalering]:
    out = []
    for map_id, label in (("watertoets_pluviaal", "pluviaal"), ("watertoets_fluviaal", "fluviaal")):
        rows = _facts(result, map_id)
        codes = []
        unknown = False
        for row in rows:
            if "gridcode" not in row:
                unknown = True
                continue
            code = str(row.get("gridcode"))
            if code != "0":
                codes.append(code)
        if not codes and not unknown:
            continue
        if codes:
            numeric = [c for c in codes if c.isdigit()]
            worst = max(numeric, key=int) if numeric else codes[0]
            description = WATERTOETS_LABELS.get(worst, f"klasse {worst}")
        else:
            description = "klasse onbekend"
        out.append(Signalering(
            "overstroming",
            f"Zone ligt in overstromingsgevoelig gebied ({label}): {description}.",
            "VMM watertoets",
            "Aandachtspunt voor het grondonderzoek: wateroverlast en hoge waterstanden bij uitvoering."))
    return out


def check_erosion(result: StudyResult) -> List[Signalering]:
    rows = [r for r in _facts(result, "erosie") if "hoog" in str(r.get("Totale_erosie", "")).lower()]
    if rows:
        distinct = sorted({str(r.get("Totale_erosie", "")) for r in rows})
        return [Signalering(
            "erosie",
            f"Totale erosie op {len(rows)} perceel/percelen in de zone: {'; '.join(distinct)}.",
            "DOV erosiekaart",
            "Aandachtspunt voor het grondonderzoek: erosiegevoelige helling; stabiliteit en afwatering.")]
    return []


def check_shrink_swell(result: StudyResult) -> List[Signalering]:
    rows = _facts(result, "krimp_zwel")
    if rows:
        distinct = sorted({str(r.get("hoofdlithologie", "")) for r in rows})
        return [Signalering(
            "krimp_zwel",
            f"Krimp-zwelgevoelige gronden op {len(rows)} perceel/percelen in de zone: {'; '.join(distinct)}.",
            "DOV plastische gronden",
            "Aandachtspunt voor het grondonderzoek: plasticiteit (Atterberg) en vochtgevoeligheid bepalen.")]
    return []


def check_ovam(result: StudyResult) -> List[Signalering]:
    rows = _facts(result, "ovam")
    if rows:
        distinct = sorted({str(r.get("uitspraak", "")) for r in rows})
        return [Signalering(
            "ovam",
            f"OVAM-uitspraken op {len(rows)} perceel/percelen in de zone: {'; '.join(distinct)}.",
            "OVAM via DOV",
            "Aandachtspunt voor het grondonderzoek: mogelijke bodemverontreiniging; "
            "bodemattest raadplegen en veiligheidsmaatregelen.")]
    return []


def check_landslide_susceptibility(result: StudyResult) -> List[Signalering]:
    graded = []
    for row in _facts(result, "grondverschuiving_gevoeligheid"):
        klasse = str(row.get("klasse") or "")
        label = str(row.get("gevoelighd") or "")
        by_class = klasse.isdigit() and int(klasse) >= LANDSLIDE_MIN_CLASS
        by_word = any(word in label.lower() for word in LANDSLIDE_WORDS)
        if by_class or by_word:
            graded.append((int(klasse) if klasse.isdigit() else 0, klasse, label))
    if not graded:
        return []
    _, klasse, label = max(graded, key=lambda item: item[0])
    grade = label or "gevoelig"
    return [Signalering(
        "grondverschuiving_gevoelig",
        f"Zone ligt in gevoelig gebied voor grondverschuivingen: {grade} (klasse {klasse or 'onbekend'}).",
        "DOV grondverschuivingen",
        "Aandachtspunt voor het grondonderzoek: hellingstabiliteit onderzoeken; sterkteparameters "
        "van de hellingslagen en grondwaterstand bepalen.")]


def check_mapped_landslides(result: StudyResult) -> List[Signalering]:
    rows = _facts(result, "grondverschuiving_gekarteerd")
    if not rows:
        return []
    named = sorted({f"{r.get('naam') or 'zonder naam'} ({r.get('type') or 'type onbekend'})" for r in rows})
    return [Signalering(
        "grondverschuiving_gekarteerd",
        f"{len(rows)} gekarteerde grondverschuiving(en) in of naast de zone: {'; '.join(named)}.",
        "DOV grondverschuivingen",
        "Aandachtspunt voor het grondonderzoek: gekarteerde grondverschuiving in of naast de zone; "
        "het DOV-rapport van de verschuiving raadplegen en de hellingstabiliteit beoordelen.")]


def check_pfas(result: StudyResult) -> List[Signalering]:
    rows = _facts(result, "pfas_no_regret")
    if not rows:
        return []
    dossiers = sorted({str(r.get("pfasdossiernr")) for r in rows if r.get("pfasdossiernr")})
    statuses = sorted({str(r.get("nrm_status_zone")) for r in rows if r.get("nrm_status_zone")})
    dossier_text = f"dossier {', '.join(dossiers)}" if dossiers else "zonder dossiernummer"
    status_text = "; ".join(statuses) if statuses else "status onbekend"
    return [Signalering(
        "pfas_no_regret",
        f"{len(rows)} PFAS-no-regretzone(s) over de zone ({dossier_text}; {status_text}).",
        "OVAM / Vlaamse overheid via DOV",
        "Aandachtspunt voor het grondonderzoek: de no-regretmaatregelen van de zone toepassen en de "
        "OVAM-richtlijnen voor grondverzet en hergebruik van uitgegraven bodem volgen.")]


def check_investigations(result: StudyResult) -> List[Signalering]:
    if not result.cpts:
        return [Signalering(
            "geen_cpt", f"Geen sonderingen binnen {result.zone.radius_m:.0f} m in DOV.", "DOV",
            "Aandachtspunt voor het grondonderzoek: geen referentiedata; volledig nieuw onderzoek nodig.")]
    near = [c for c in result.cpts if c.distance_m <= 50.0]
    if near:
        return [Signalering(
            "cpt_dichtbij", f"{len(near)} sondering(en) binnen 50 m van de zone.", "DOV",
            "Bestaande data bruikbaar als referentie voor het onderzoeksprogramma.", severity="info")]
    return []


def check_relief(result: StudyResult) -> List[Signalering]:
    if result.relief is None:
        return []
    lo, hi, _ = result.relief
    if hi - lo > 2.0:
        return [Signalering(
            "relief", f"Maaiveld varieert van {lo:.1f} tot {hi:.1f} mTAW in de zone.", "DHMV II",
            "Aandachtspunt voor het grondonderzoek: reliefverschil; niveaus van proeven nauwkeurig inmeten.")]
    return []


def check_sources(result: StudyResult) -> List[Signalering]:
    return [Signalering(
        "bron_niet_beschikbaar", f"Bron niet beschikbaar: {p.message}", p.source,
        "Hoofdstuk onvolledig; bron later opnieuw raadplegen.", severity="aandacht")
        for p in result.provenance if not p.ok]


RULES: List[Rule] = [
    check_anthropogenic, check_soft_layers, check_shallow_tertiary, check_soil_map, check_groundwater,
    check_flood, check_erosion, check_shrink_swell, check_ovam, check_landslide_susceptibility,
    check_mapped_landslides, check_pfas, check_investigations, check_relief, check_sources,
]


def run_all(result: StudyResult) -> List[Signalering]:
    out: List[Signalering] = []
    for rule in RULES:
        for sig in rule(result):
            if sig.severity not in SEVERITIES:
                raise ValueError(f"onbekende severity {sig.severity!r} voor signalering {sig.code!r}")
            out.append(sig)
    return out
