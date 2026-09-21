"""Fact-driven signalling rules. Each rule: StudyResult -> list[Signalering]. No judgement,
only facts + source + a fixed attention sentence for the ground investigation."""
from __future__ import annotations

import re
from typing import Callable, List, Optional, Sequence, Tuple

from . import catalogue, lithology
from .catalogue import WATERTOETS_LABELS
from .model import Signalering, StudyResult, VirtualBorehole
from .services.virtuele_boring import layers_named

SOFT_WORDS = re.compile(r"\b(klei|veen|leem)\b")
WET_DRAINAGE = {"e", "f", "g", "h", "i"}
SOFT_TEXTURES = {"V", "E", "U"}
BUILT_UP_PREFIXES = ("OB", "ON", "OT", "OE")
# DOV grades landslide susceptibility as klasse "1".."3" with a matching Dutch label - live
# check 2026-09-15 over the Flemish Ardennes: exactly "lage"/"matige"/"hoge gevoeligheid". The
# label carries the same grade as the digit, so it is ranked on the same 1..3 scale and a row
# takes the worse of the two; from class 2 ("matige gevoeligheid") upwards the slope is worth
# investigating. The labels are inflected, so match "hoge"/"lage" beside "hoog"/"laag", and test
# the worst word first so "zeer hoge gevoeligheid" cannot be read as low.
LANDSLIDE_MIN_CLASS = 2
LANDSLIDE_WORD_CLASSES = (("hoog", 3), ("hoge", 3), ("matig", 2), ("laag", 1), ("lage", 1))
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


SHALLOW_GHG_M = 2.0


def check_modelled_groundwater(result: StudyResult) -> List[Signalering]:
    """The modelled mean highest groundwater level, when it sits shallow enough to plan around.

    Same threshold as the measured filter above, because it is the same question - can you dig
    here without meeting water - and the same attention sentence. The difference is the source,
    and the rule says so: this is a regional model, not a standpipe on the plot.
    """
    rows = _facts(result, "gxg_ghg")
    depth = next((row.get("GHG-waarde_m-mv") for row in rows
                  if row.get("GHG-waarde_m-mv") is not None), None)
    if depth is None or float(depth) >= SHALLOW_GHG_M:
        return []
    return [Signalering(
        "ondiepe_ghg",
        f"Modelwaarde GHG: {float(depth):.2f} m onder maaiveld (gemiddeld hoogste "
        f"grondwaterstand).",
        "DOV GxG-kaart (modelwaarde, geen peilbuismeting)",
        "Aandachtspunt voor het grondonderzoek: ondiepe grondwaterstand; bemaling en "
        "waterspanningen meenemen, en de modelwaarde ter plaatse laten meten.")]


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


def _landslide_grade(row) -> Tuple[int, str, str]:
    """(grade, klasse, label) for one susceptibility row. The digit class and the Dutch label are
    two spellings of the same grade, so the row takes whichever of the two is worse: a row labelled
    "hoge gevoeligheid" without a digit class still outranks a plain class 2."""
    klasse = str(row.get("klasse") or "")
    label = str(row.get("gevoelighd") or "")
    lowered = label.lower()
    by_word = next((rank for word, rank in LANDSLIDE_WORD_CLASSES if word in lowered), 0)
    by_class = int(klasse) if klasse.isdigit() else 0
    return max(by_class, by_word), klasse, label


def check_landslide_susceptibility(result: StudyResult) -> List[Signalering]:
    graded = [_landslide_grade(row) for row in _facts(result, "grondverschuiving_gevoeligheid")]
    graded = [grade for grade in graded if grade[0] >= LANDSLIDE_MIN_CLASS]
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
    # one landslide is mapped as several polygons, so the row count and the number of distinct
    # names are different figures; reporting only the first would overstate how many there are
    named = sorted({f"{r.get('naam')} ({r.get('type') or 'type onbekend'})" for r in rows if r.get("naam")})
    detail = f"{len(named)} met naam: {'; '.join(named)}" if named else "geen enkele met een naam"
    return [Signalering(
        "grondverschuiving_gekarteerd",
        f"{len(rows)} gekarteerde grondverschuiving(en) in of naast de zone ({detail}).",
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


# Welk hoofdstuk een kaart draagt, in de woorden waarmee het rapport dat hoofdstuk noemt. De
# nummers en titels staan in `report_content`; hier alleen de titel, want de lezer zoekt op naam.
CHAPTER_TITLES = {"ligging": "1 Ligging en topografie", "historisch": "2 Historische kaarten",
                  "geologie": "3 Geologie en bodem"}
# Bronregels die bij een kaart horen dragen haar titel achter een vast voorvoegsel. De tekeningen
# van de profieltypes horen bij de quartairkaart, en die staat in hoofdstuk 3.
DRAWING_PREFIXES = ("Legenda profieltype", "Eenhedentabel kaartblad")


def _chapter_of(source: str) -> str:
    """Het hoofdstuk dat deze bron draagt, of "" als het er geen enkel is.

    De lezer vroeg zich af WELK hoofdstuk iets mist: "Hoofdstuk onvolledig" zonder naam laat hem
    het bronnenhoofdstuk achterin uitpluizen om dat zelf uit te zoeken.
    """
    if source.startswith(DRAWING_PREFIXES):
        return CHAPTER_TITLES["geologie"]
    for entry in catalogue.entries(enabled_only=False):
        if entry.title and entry.title in source:
            return CHAPTER_TITLES.get(entry.chapter, "")
    return ""


def check_sources(result: StudyResult) -> List[Signalering]:
    out = []
    for p in result.provenance:
        if p.ok:
            continue
        chapter = _chapter_of(p.source)
        where = f"Hoofdstuk {chapter} is onvolledig" if chapter else "Het rapport is onvolledig"
        out.append(Signalering(
            "bron_niet_beschikbaar", f"Bron niet beschikbaar: {p.message}", p.source,
            f"{where}; bron later opnieuw raadplegen.", severity="aandacht"))
    return out


def check_borehole_remarks(result: StudyResult) -> List[Signalering]:
    """What the borehole descriptions name that is not the ordinary matrix, per borehole.

    Reporting, never interpretation: the word the description used, the depth it was first named
    at and the sentence itself, quoted. What sandstone concretions or a peat layer MEAN for a
    foundation is a conclusion, and this plugin does not draw conclusions - the fixed attention
    sentence sends it to the ground investigation, like every other rule here.

    One signal per borehole, not per word: five words from one description are one observation
    about one borehole, and a table with a row per word is a table nobody reads.
    """
    out: List[Signalering] = []
    for borehole in result.boreholes:
        terms = lithology.notable_terms(borehole.lithology)
        if not terms:
            continue
        named = lithology.summarise(terms)
        quote = terms[0].quote
        out.append(Signalering(
            "boring_opmerking",
            f"De beschrijving van boring {borehole.number} vermeldt {named}; "
            f"op {terms[0].depth} staat er: \"{quote}\".",
            f"DOV boring {borehole.number}",
            "Aandachtspunt voor het grondonderzoek: laat deze waarneming ter plaatse nakijken."))
    return out


RULES: List[Rule] = [
    check_anthropogenic, check_soft_layers, check_shallow_tertiary, check_soil_map, check_groundwater,
    check_modelled_groundwater,
    check_flood, check_erosion, check_shrink_swell, check_ovam, check_landslide_susceptibility,
    check_mapped_landslides, check_pfas, check_investigations, check_relief, check_sources,
    check_borehole_remarks,
]


def validate(signals: Sequence[Signalering]) -> List[Signalering]:
    """Guard the severity vocabulary for every signal that reaches the report, wherever it came
    from. The rules below are not the only source: the orchestrator adds its own (WFS truncation,
    an incomplete section), and a typo in one of those must not slip into the summary table."""
    for sig in signals:
        if sig.severity not in SEVERITIES:
            raise ValueError(f"onbekende severity {sig.severity!r} voor signalering {sig.code!r}")
    return list(signals)


def run_all(result: StudyResult) -> List[Signalering]:
    out: List[Signalering] = []
    for rule in RULES:
        out.extend(rule(result))
    return validate(out)
