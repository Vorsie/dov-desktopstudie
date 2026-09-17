from __future__ import annotations

import pytest

from desktopstudie.core import report_content as rc
from desktopstudie.core.model import (
    Cpt,
    MapFact,
    Signalering,
    StudyResult,
    StudyZone,
    VbLayer,
    VirtualBorehole,
)
from tests import quartair


def _result(gent_ring):
    r = StudyResult(zone=StudyZone(ring=gent_ring, name="Gent test", address="Kortrijksesteenweg 100, Gent"),
                    created_at="2026-09-15T10:00:00")
    r.municipality = "Gent"
    r.cpts = [Cpt("1965-039716", "SIX", 104007.0, 192682.0, 6.26, 20.4, "1965-02-17", "discontinu mechanisch", "M4",
                  "RIG", "GEO-64/306", "https://www.dov.vlaanderen.be/data/sondering/1965-039716", 210.0)]
    r.map_facts.append(MapFact("bodemkaart", "Bodemkaart van Vlaanderen", [
        {"Bodemtype": "OB", "Bodemserie": "OB", "Beknopte_omschrijving_bodemserie": "Bebouwde zones",
         "Textuurklasse": None, "Drainageklasse": None, "Gegeneraliseerde_legende": "Antropogeen",
         "Textuurklasse_code": None, "Drainageklasse_code": None}]))
    r.signaleringen.append(Signalering("geen_cpt", "feit", "bron", "advies"))
    r.figures["cpt_1965-039716"] = "figuren/cpt_1965-039716.png"
    return r


def test_chapters_follow_the_design_order(gent_ring):
    report = rc.build_report(_result(gent_ring), rc.ReportMeta(project="P1", author="A", company="C"))
    titles = [ch.title for ch in report.chapters]
    assert titles == ["Ligging en topografie", "Historische kaarten", "Geologie en bodem", "Virtuele boring",
                      "Grondonderzoek DOV", "Doorsnede", "Samenvatting en aandachtspunten", "Bronnen en licenties"]


def test_map_pages_come_from_catalogue_and_tables_from_data(gent_ring):
    report = rc.build_report(_result(gent_ring), rc.ReportMeta(project="P1", author="A", company="C"))
    hist = report.chapters[1]
    assert [p.map_id for p in hist.pages if isinstance(p, rc.MapPage)][:4] == ["ferraris", "abw", "vandermaelen",
                                                                               "popp"]
    assert hist.pages[0].scale == 25000  # low-resolution map: zoomed out further than the GRB page
    geo = report.chapters[2]
    # chapter 3 interleaves: map page, how to read its codes, then what lies in the zone
    assert isinstance(geo.pages[0], rc.MapPage) and geo.pages[0].map_id == "bodemkaart"
    assert geo.pages[0].guide.title.startswith("Leeswijzer")
    legend = geo.pages[0].zone_legend  # onder de kaart, niet op een blad ernaast
    assert legend.title == "Legenda voor de zone - Bodemkaart van Vlaanderen"
    assert legend.rows[0][0] == "OB"
    assert legend.columns[2] == "Omschrijving"  # readable header, not the raw DOV field name
    inv = report.chapters[4]
    cpt_table = next(p for p in inv.pages if isinstance(p, rc.TablePage) and p.title.startswith("Sonderingen"))
    assert cpt_table.columns[0] == "Nummer" and cpt_table.rows[0][1] == "210"
    # Korte kop: "Afstand (m)" is drie keer zo breed als het getal eronder en duwt de laatste
    # kolom van het blad af. De tabel heeft negen kolommen; elke millimeter telt.
    assert cpt_table.columns[1] == "Afst. (m)"
    assert cpt_table.columns[-1] == "DOV-fiche" and cpt_table.rows[0][-1] == "1965-039716"
    assert cpt_table.links[0] == "https://www.dov.vlaanderen.be/data/sondering/1965-039716"
    figs = [p for p in inv.pages if isinstance(p, rc.FigurePage)]
    assert figs and figs[0].image_path.endswith("cpt_1965-039716.png")
    overview = next(p for p in inv.pages if isinstance(p, rc.MapPage))
    assert overview.scale == 5000 and overview.show_investigations


def test_summary_chapter_lists_signaleringen_and_sources_page_lists_provenance(gent_ring):
    r = _result(gent_ring)
    report = rc.build_report(r, rc.ReportMeta(project="P1", author="A", company="C"))
    summary = report.chapters[6]
    sig_table = next(p for p in summary.pages if isinstance(p, rc.TablePage) and p.title == "Signaleringen")
    assert sig_table.rows[0][0] == "feit"
    assert report.meta["project"] == "P1" and report.meta["address"] == "Kortrijksesteenweg 100, Gent"


def test_empty_result_builds_without_crash_and_explains_gaps(gent_ring):
    r = StudyResult(zone=StudyZone(ring=gent_ring, name="Leeg"), created_at="t")
    report = rc.build_report(r, rc.ReportMeta(project="P1", author="A", company="C"))
    vb_chapter = report.chapters[3]
    assert any(isinstance(p, rc.TextPage) and "niet beschikbaar" in p.html for p in vb_chapter.pages)
    inv = report.chapters[4]
    empty_tables = [p for p in inv.pages if isinstance(p, rc.TablePage) and not p.rows]
    assert empty_tables and all(t.note for t in empty_tables)
    sec = report.chapters[5]
    assert any(isinstance(p, rc.MapPage) for p in sec.pages)
    assert any(isinstance(p, rc.TextPage) and "niet beschikbaar" in p.html for p in sec.pages)


def test_chapter_4_falls_back_when_no_virtual_borehole_has_layers(gent_ring):
    # A model that answered with zero layers is not a virtual borehole; showing its empty table
    # instead of the fallback text would read as "the ground here has no geology".
    r = _result(gent_ring)
    r.virtual_boreholes["g3dv3_F"] = VirtualBorehole(x=0.0, y=0.0, model="g3dv3_F", layers=[])
    vb_chapter = rc.build_report(r, rc.ReportMeta(project="P1", author="A", company="C")).chapters[3]
    assert any(isinstance(p, rc.TextPage) and "niet beschikbaar" in p.html for p in vb_chapter.pages)
    assert not any(isinstance(p, rc.TablePage) for p in vb_chapter.pages)


def test_an_empty_virtual_borehole_table_says_why_it_is_empty(gent_ring):
    r = _result(gent_ring)
    r.virtual_boreholes["g3dv3_F"] = VirtualBorehole(x=0.0, y=0.0, model="g3dv3_F", layers=[
        VbLayer("g3dv3_F_2", "Formatie van Gent", 14.6, 10.0, 4.6, "#FFFF00", "dekzand")])
    r.virtual_boreholes["hcovv2_S"] = VirtualBorehole(x=0.0, y=0.0, model="hcovv2_S", layers=[])
    vb_chapter = rc.build_report(r, rc.ReportMeta(project="P1", author="A", company="C")).chapters[3]
    tables = {p.title: p for p in vb_chapter.pages if isinstance(p, rc.TablePage)}
    filled = next(t for title, t in tables.items() if "G3Dv3" in title)
    empty = next(t for title, t in tables.items() if "HCOV" in title)
    assert filled.rows and filled.note == ""
    assert empty.rows == [] and empty.note == "Geen modellagen op dit punt."


def test_meta_has_no_none_values(gent_ring):
    r = StudyResult(zone=StudyZone(ring=gent_ring, name="Leeg"), created_at="t")
    report = rc.build_report(r, rc.ReportMeta(project="P1", author="A", company="C"))
    assert all(v is not None for v in report.meta.values())
    assert "representative_point" in report.meta and "disclaimer" in report.meta


def test_the_bomb_map_slot_and_the_manual_check_name_the_explosives_risk(gent_ring):
    """De bommenkaart krijgt geen blad tussen de historische kaarten - de manuele controle zegt al
    wat de lezer moet doen - maar de bronnenlijst noemt haar met de reden."""
    report = rc.build_report(_result(gent_ring), rc.ReportMeta(project="P1", author="A", company="C"))
    hist = report.chapters[1]
    assert not any(isinstance(p, rc.MapPage) and p.map_id == "bommenkaart" for p in hist.pages)
    manual = next(p for p in hist.pages if p.title.startswith("Manuele controle"))
    assert "conventionele en toxische explosieven" in manual.html
    assert "bommenkaart.be" in manual.html and "DOVO" in manual.html

    left_out = next(p for p in report.chapters[7].pages if p.title.startswith("Niet opgenomen"))
    bombs = next(row for row in left_out.rows if "ommenkaart" in row[0])
    assert "geen open data" in bombs[1] and "explosieven" in bombs[1]


def test_the_new_geology_maps_get_a_map_page_and_a_zone_legend(gent_ring):
    report = rc.build_report(_result(gent_ring), rc.ReportMeta(project="P1", author="A", company="C"))
    geo = report.chapters[2]
    map_ids = [p.map_id for p in geo.pages if isinstance(p, rc.MapPage)]
    assert {"grondverschuiving_gevoeligheid", "grondverschuiving_gekarteerd", "pfas_no_regret"} <= set(map_ids)
    pfas = _zone_legend(geo, "PFAS")
    # "(bron)", niet "(link)": de ingekorte URL noemt de bron, ze is niet meer aan te klikken - het
    # fragment (#sb-...) waar de maatregel zelf staat, valt bij het inkorten weg.
    assert pfas.columns == ["PFAS-dossier", "Gemeente", "Straat", "Status", "Geldig vanaf",
                            "Maatregelen (bron)"]


def test_the_sources_table_prints_a_date_and_a_short_url(gent_ring):
    """Een volledige tijdstempel met tijdzone ("2026-09-15T22:21:09+02:00") en een URL met de hele
    CQL-polygoon erin passen op geen blad: ze worden afgekapt en zeggen dan niets meer. De datum en
    de dienst zijn wat de lezer nodig heeft om een bron terug te vinden."""
    from desktopstudie.core.model import Provenance

    result = _result(gent_ring)
    result.provenance = [Provenance(
        "Sonderingen",
        "https://www.dov.vlaanderen.be/geoserver/wfs?service=WFS&request=GetFeature"
        "&typeNames=dov-pub%3ASonderingen&CQL_FILTER=DWITHIN%28geom%2CPOLYGON%28%28104226%20192406"
        "%2C104426%20192406%29%29%2C500%2Cmeters%29",
        "2026-09-15T22:21:09+02:00", True)]
    report = rc.build_report(result, rc.ReportMeta(project="T", author="A", company="B"))

    sources = next(p for p in report.chapters[7].pages if p.title.startswith("Geraadpleegde"))
    row = sources.rows[0]
    assert row[2] == "2026-09-15"
    assert "CQL_FILTER" not in row[1] and row[1].startswith("https://www.dov.vlaanderen.be/geoserver/wfs")


def _with_quartair(result, codes=("22026", "22010", "22026", "22098")):
    """De quartairrijen zoals de WFS ze levert: een rij per kaartvlak, dus hetzelfde profieltype
    kan twee keer in de zone liggen. De eerste twee cijfers van de code zijn het kaartblad."""
    result.map_facts.append(quartair.map_fact(codes))
    return result


def _profile_images(*codes, sheets=("22",)):
    """Wat de schil aanlevert: een kopstrook per profieltype en een eenhedentabel per kaartblad."""
    images = {rc.profile_image_key(code): f"legendas/quartair_{code}_kop.png" for code in codes}
    images.update({rc.sheet_image_key(sheet): f"legendas/quartair_kaartblad_{sheet}.png"
                   for sheet in sheets})
    return images


def _geologie(result, zone_legend_images=None):
    return rc.build_report(result, rc.ReportMeta(project="P1", author="A", company="C"),
                           zone_legend_images=zone_legend_images).chapters[2]


def _zone_legend(chapter, title_part):
    """De legenda voor de zone van een kaart, waar ze staat: onder het kaartkader van haar eigen
    kaartpagina, niet als blad in het hoofdstuk."""
    return next(page.zone_legend for page in chapter.pages
                if isinstance(page, rc.MapPage) and page.zone_legend is not None
                and title_part in page.zone_legend.title)


def test_the_zone_legend_lists_only_the_classes_that_lie_in_the_zone(gent_ring):
    """De volledige bodemlegende telt honderden series; de lezer heeft er een nodig. "Legenda voor
    de zone" zet de klassen die in deze zone voorkomen op een rij, met hun omschrijving erbij."""
    geo = _geologie(_result(gent_ring))

    legend = _zone_legend(geo, "Bodemkaart van Vlaanderen")
    # De gegeneraliseerde legende ("Antropogeen") zegt iets wat geen andere kolom zegt en verhuist
    # mee nu de feitentabel verdwijnt; de textuur- en drainagecode herhalen alleen hun eigen naam.
    assert legend.columns == ["Bodemtype", "Serie", "Omschrijving", "Textuur", "Drainage", "Legende"]
    assert legend.rows == [["OB", "OB", "Bebouwde zones", "-", "-", "Antropogeen"]]


def test_the_reading_guide_travels_on_its_own_map(gent_ring):
    """De volgorde waarin de lezer het nodig heeft, en allemaal op een blad: de kaart, hoe haar
    codes te lezen zijn (de leeswijzer) en welke klassen er in de zone liggen."""
    geo = _geologie(_result(gent_ring))

    bodemkaart = next(p for p in geo.pages
                      if isinstance(p, rc.MapPage) and p.map_id == "bodemkaart")
    page = bodemkaart.guide
    assert isinstance(page, rc.TextPage)
    assert "Z zand" in page.html and "drainage" in page.html
    assert '<a href="https://www.dov.vlaanderen.be/page/' in page.html, "de link hoort klikbaar te zijn"
    assert bodemkaart.zone_legend is not None


def test_the_quartair_zone_legend_carries_a_strip_per_profile_type(gent_ring):
    """Twee kaartvlakken van hetzelfde profieltype zijn een legenda-eenheid. En wat een lezer nodig
    heeft is de tekening zelf - kleurvlak, lettercode, omschrijving - niet een URL van 145 tekens en
    niet "zie hierna": de kopstrook van DOV staat op de legendapagina zelf, met code en kaartblad
    ernaast."""
    geo = _geologie(_with_quartair(_result(gent_ring)),
                    zone_legend_images=_profile_images("22026", "22010", "22098"))

    legend = _zone_legend(geo, "Quartairgeologische kaart 1/50 000")
    assert isinstance(legend, rc.LegendPage)
    assert [(e.code, e.sheet, e.image_path) for e in legend.entries] == [
        ("22026", "22", "legendas/quartair_22026_kop.png"),
        ("22010", "22", "legendas/quartair_22010_kop.png"),
        ("22098", "22", "legendas/quartair_22098_kop.png")]
    assert legend.note == ""


def test_a_profile_type_whose_drawing_failed_keeps_its_line(gent_ring):
    """De kern haalt niets op. Kreeg ze geen pad voor een profieltype, dan blijft de regel staan -
    code en kaartblad kloppen nog - alleen de tekening ontbreekt, en de bronnenlijst zegt waarom."""
    geo = _geologie(_with_quartair(_result(gent_ring)), zone_legend_images=_profile_images("22026"))

    legend = _zone_legend(geo, "Quartairgeologische kaart 1/50 000")
    assert [(e.code, e.image_path) for e in legend.entries] == [
        ("22026", "legendas/quartair_22026_kop.png"), ("22010", ""), ("22098", "")]


def test_the_quartair_block_is_two_pages_not_four(gent_ring):
    """Vier bladen voor twee profieltypes - een tabel met "zie hierna", twee bijna lege strookjes en
    de eenhedentabel - is er twee te veel. De strookjes horen op de legendapagina; wat overblijft is
    die pagina plus de eenhedentabel van het kaartblad."""
    geo = _geologie(_with_quartair(_result(gent_ring)),
                    zone_legend_images=_profile_images("22026", "22010", "22098"))

    titles = [p.title for p in geo.pages]
    assert not any(title.startswith("Profieltype ") for title in titles), titles
    quartair = [title for title in titles if "1/50 000 (samengesteld)" in title
                or title.startswith("Eenheden op kaartblad")]
    assert quartair == ["Quartairgeologische kaart 1/50 000 (samengesteld)",
                        "Eenheden op kaartblad 22"]


def test_the_sheet_units_page_names_what_it_is_valid_for(gent_ring):
    """De eenhedentabel geldt voor elk profieltype van dat blad; dat hoort onder de tekening te
    staan, anders leest ze als de tabel van het profieltype dat er toevallig boven stond."""
    geo = _geologie(_with_quartair(_result(gent_ring)),
                    zone_legend_images=_profile_images("22026", "22010", "22098"))

    units = next(p for p in geo.pages if p.title == "Eenheden op kaartblad 22")
    assert isinstance(units, rc.FigurePage)
    assert units.image_path == "legendas/quartair_kaartblad_22.png"
    assert units.caption == ("Eenheden van kaartblad 22, geldig voor elk profieltype van dat "
                             "blad - DOV")


def test_a_profile_type_code_names_its_map_sheet():
    """Het kaartblad is de eerste twee cijfers van de code: 22010 ligt op kaartblad 22."""
    assert rc.quartair_sheet("22010") == "22"
    assert rc.quartair_sheet("3a") == "3a", "een korte code is zelf het blad, niet de helft ervan"


def test_an_empty_zone_legend_says_whether_the_zone_or_the_source_was_empty(gent_ring):
    """Een kaart die niets in de zone heeft, en een kaart die niet antwoordde, zien er allebei leeg
    uit. Ze mogen niet hetzelfde lezen: een platte dienst als "geen eenheden" melden is een
    onwaarheid over de zone."""
    result = _result(gent_ring)
    result.map_facts.append(MapFact("tertiair", "Tertiairgeologische kaart 1/50 000", []))

    geo = _geologie(result)

    empty = _zone_legend(geo, "Tertiairgeologische kaart")
    assert empty.rows == [] and empty.note == "Geen kaarteenheden binnen de zone."
    silent = _zone_legend(geo, "HCOV")
    assert silent.rows == [] and silent.note == "Bron niet beschikbaar."


def test_a_map_without_a_fact_table_still_gets_its_reading_guide(gent_ring):
    """Het hoogtemodel somt niets op - er zijn geen kaarteenheden - maar de kleurschaal vraagt wel
    uitleg. Die leeswijzer staat onder het kaartkader; een kaart zonder codes krijgt er geen."""
    report = rc.build_report(_result(gent_ring), rc.ReportMeta(project="P1", author="A", company="C"))

    pages = report.chapters[0].pages
    dtm = next(p for p in pages if isinstance(p, rc.MapPage) and p.map_id == "dhmv_dtm")
    assert dtm.guide.title == "Leeswijzer - Digitaal Hoogtemodel Vlaanderen II - DTM 1 m"
    ferraris = next(p for p in report.chapters[1].pages
                    if isinstance(p, rc.MapPage) and p.map_id == "ferraris")
    assert ferraris.guide is None


def test_a_zone_legend_url_is_printed_in_its_short_form(gent_ring):
    """Een URL draagt geen spaties, dus een tabel kan ze niet afbreken: ze past of ze wordt midden
    in een woord afgekapt. Waar een legenda voor de zone een link toont - de PFAS-maatregelen -
    staat daarom de ingekorte vorm."""
    result = _result(gent_ring)
    result.map_facts.append(MapFact("pfas_no_regret", "PFAS - no-regretmaatregelen", [
        {"pfasdossiernr": "93685", "gemeente": "Zwijndrecht", "straat": "Gavers",
         "nrm_status_zone": "Locatiespecifiek vastgesteld", "zone_geldig_vanaf": "2022-05-03",
         "no_regret_maatregelen": "https://www.vlaanderen.be/pfas-vervuiling/beveren-kruibeke-"
                                  "zwijndrecht-no-regret-maatregelen#sb-no-regret-maatregelen-"
                                  "kwartier-brosius-cf0a2df6-d1a5-4da4-a9bd-573932286d4b"}]))

    geo = _geologie(result)

    legend = _zone_legend(geo, "PFAS")
    link = legend.rows[0][-1]
    assert link.startswith("https://www.vlaanderen.be/...") and len(link) <= 64, link


def test_a_map_gets_one_table_not_two(gent_ring):
    """De feitentabel en de legenda voor de zone zeiden hetzelfde: dezelfde rij OB op twee bladen,
    en voor het Quartair een kolom met een URL die niemand kan gebruiken. Waar een legenda voor de
    zone bestaat, vervangt ze de feitentabel - de rauwe rijen blijven in studie.json staan."""
    report = rc.build_report(_with_quartair(_result(gent_ring)),
                             rc.ReportMeta(project="P1", author="A", company="C"))

    geo = report.chapters[2]
    titles = [p.title for p in geo.pages]
    assert not any(title.endswith("eenheden in de zone") for title in titles), titles
    assert _zone_legend(geo, "Bodemkaart van Vlaanderen").rows
    # en de kern houdt de rijen zoals de dienst ze gaf
    rows = next(fact.rows for fact in _with_quartair(_result(gent_ring)).map_facts
                if fact.map_id == "quartair")
    assert rows[0]["legende"].startswith("https://datasets.omgeving.vlaanderen.be/be.vlaanderen")


def test_a_generic_zone_legend_translates_its_codes(gent_ring):
    """Wat de feitentabel deed, doet de legenda voor de zone nu: de vertaling van de catalogus met
    de rauwe code van de dienst ernaast, zodat een lezer ze kan narekenen."""
    result = _result(gent_ring)
    result.map_facts.append(MapFact("watertoets_pluviaal", "Watertoets - pluviaal",
                                    [{"gridcode": "2"}, {"gridcode": "2"}]))

    geo = _geologie(result)

    legend = _zone_legend(geo, "Watertoets")
    assert legend.columns == ["Klasse"]
    assert legend.rows == [["C - Kleine kans op overstromingen [2]"]], "ontdubbeld en vertaald"


def test_a_source_that_answered_but_has_nothing_here_says_why(gent_ring):
    """Een historisch mozaiek zonder blad voor deze gemeente antwoordt netjes - HTTP 200, lege
    tegel. Dat is geen fout, maar "ok" alleen laat de lezer met een wit blad en geen uitleg
    zitten."""
    from desktopstudie.core.model import Provenance

    result = _result(gent_ring)
    result.provenance = [
        Provenance("Kaartlaag Popp", "https://geo.api.vlaanderen.be/HISTCART/wms", "2026-09-16T08:00:00",
                   True, "geen dekking op deze locatie"),
        Provenance("Kaartlaag GRB", "https://geo.api.vlaanderen.be/GRB-basiskaart/wms",
                   "2026-09-16T08:00:00", True),
        Provenance("Sonderingen", "https://www.dov.vlaanderen.be/geoserver/wfs", "2026-09-16T08:00:00",
                   False, "HTTP 500")]

    sources = next(p for p in rc.build_report(result, rc.ReportMeta(project="T", author="A", company="B"))
                   .chapters[7].pages if p.title.startswith("Geraadpleegde"))

    assert [row[3] for row in sources.rows] == ["ok - geen dekking op deze locatie", "ok",
                                                "fout: HTTP 500"]


def test_an_unchosen_map_gets_no_sheet(gent_ring):
    """Een kaart die niet gekozen is, krijgt geen blad.

    De kaartenchecklist van de dialoog belooft dat letterlijk (README): wie Popp en de bodemkaart
    uitvinkt, hoort ze nergens in het rapport terug te zien - ook hun leeswijzer en hun legenda
    voor de zone niet, want die horen bij het blad dat er niet is.
    """
    from desktopstudie.core import catalogue

    result = _result(gent_ring)
    result.map_ids = [e.id for e in catalogue.entries() if e.id not in ("popp", "bodemkaart")]

    report = rc.build_report(result, rc.ReportMeta(project="P1", author="A", company="C"))

    maps = [p.map_id for ch in report.chapters for p in ch.pages if isinstance(p, rc.MapPage)]
    assert "popp" not in maps and "bodemkaart" not in maps
    assert "ferraris" in maps and "quartair" in maps
    titles = [p.title for ch in report.chapters for p in ch.pages]
    assert not any("Bodemkaart van Vlaanderen" in title for title in titles), titles


def test_an_unchosen_map_is_not_in_the_sources_list(gent_ring):
    """Een kaart die niet gekozen is, staat niet in de bronnenlijst.

    De tabel Kaartbronnen en licenties zegt welke kaarten de studie heeft geraadpleegd; een kaart
    die nooit is opgehaald hoort daar niet in, anders leest de lezer een licentie voor een blad
    dat niet bestaat.
    """
    from desktopstudie.core import catalogue

    result = _result(gent_ring)
    result.map_ids = [e.id for e in catalogue.entries() if e.id != "popp"]

    sources = next(p for p in rc.build_report(result, rc.ReportMeta(project="P1", author="A", company="C"))
                   .chapters[7].pages if p.title.startswith("Kaartbronnen"))

    assert not any(row[0] == catalogue.by_id("popp").title for row in sources.rows), sources.rows
    assert any(row[0] == catalogue.by_id("ferraris").title for row in sources.rows)


def test_without_a_choice_every_enabled_map_stays_in_the_report(gent_ring):
    """Zonder keuze blijven alle ingeschakelde kaarten in het rapport.

    `map_ids is None` is de standaard van de kern en van de dialoog zodra alles aangevinkt staat;
    het filter mag dan niets wegnemen.
    """
    from desktopstudie.core import catalogue

    result = _result(gent_ring)
    assert result.map_ids is None

    report = rc.build_report(result, rc.ReportMeta(project="P1", author="A", company="C"))

    maps = {p.map_id for ch in report.chapters for p in ch.pages if isinstance(p, rc.MapPage)}
    assert maps == {e.id for e in catalogue.entries()}
    sources = next(p for p in report.chapters[7].pages if p.title.startswith("Kaartbronnen"))
    assert len(sources.rows) == len(catalogue.entries())


# --- de legenda voor de zone staat onder haar kaart -------------------------------------------

def test_the_zone_legend_stands_under_its_map_and_not_on_a_sheet_of_its_own(gent_ring):
    """Een apart blad "Legenda voor de zone" draagt vaak een of twee regels en laat de rest van de
    A4 wit. Die legenda hoort onder het kaartkader op het kaartblad zelf te staan, dus ze is geen
    pagina van het hoofdstuk meer - ze reist mee met haar kaart."""
    geo = _geologie(_result(gent_ring))

    assert not [p for p in geo.pages if p.title.startswith("Legenda voor de zone")], \
        "de zonelegenda hoort geen eigen blad meer te zijn"
    bodemkaart = next(p for p in geo.pages if isinstance(p, rc.MapPage) and p.map_id == "bodemkaart")
    legend = bodemkaart.zone_legend
    assert isinstance(legend, rc.TablePage)
    assert legend.title == "Legenda voor de zone - Bodemkaart van Vlaanderen"
    assert legend.rows == [["OB", "OB", "Bebouwde zones", "-", "-", "Antropogeen"]]


def test_the_quartair_zone_legend_takes_its_drawings_under_the_map_too(gent_ring):
    """De zonelegenda van het Quartair draagt tekeningen - de kopstroken van de profieltypes. Ook
    die gaan onder de kaart mee; alleen de eenhedentabel van het kaartblad blijft een eigen blad,
    want dat is een tekening van een halve A4."""
    geo = _geologie(_with_quartair(_result(gent_ring)),
                    zone_legend_images=_profile_images("22026", "22010", "22098"))

    quartair_map = next(p for p in geo.pages if isinstance(p, rc.MapPage) and p.map_id == "quartair")
    legend = quartair_map.zone_legend
    assert isinstance(legend, rc.LegendPage)
    assert [(e.code, e.sheet) for e in legend.entries] == [("22026", "22"), ("22010", "22"),
                                                           ("22098", "22")]
    assert [p.title for p in geo.pages if p.title.startswith("Eenheden op kaartblad")] == [
        "Eenheden op kaartblad 22"]


def test_a_map_without_a_zone_legend_carries_none(gent_ring):
    """Een kaart zonder feiten - een orthofoto, het hoogtemodel - heeft geen legenda voor de zone;
    ze draagt er dan ook geen."""
    report = rc.build_report(_result(gent_ring), rc.ReportMeta(project="P1", author="A", company="C"))

    ortho = next(p for p in report.chapters[0].pages
                 if isinstance(p, rc.MapPage) and p.map_id == "ortho")
    assert ortho.zone_legend is None


# --- de kleurschaal van het hoogtemodel --------------------------------------------------------

def test_the_dem_map_carries_a_colour_ramp_with_the_zone_values_under_it(gent_ring):
    """De legenda van het DHMV is een kleurbalk over heel Vlaanderen; een heel blad daarvoor leest
    niemand. Ze hoort als strookje onder de kaart, met de laagste, de gemiddelde en de hoogste
    hoogte van de zone zelf erbij - die drie staan al in `StudyResult.relief`."""
    result = _result(gent_ring)
    result.relief = (6.84, 9.40, 8.12)

    report = rc.build_report(result, rc.ReportMeta(project="P1", author="A", company="C"),
                             zone_legend_images={rc.ramp_image_key("dhmv_dtm"):
                                                 "legendas/dhmv_dtm_schaal.png"})

    dtm = next(p for p in report.chapters[0].pages
               if isinstance(p, rc.MapPage) and p.map_id == "dhmv_dtm")
    ramp = dtm.ramp
    assert ramp.image_path == "legendas/dhmv_dtm_schaal.png"
    assert ramp.low == "-50 mTAW" and ramp.high == "300 mTAW", "de uiteinden van de dienst zelf"
    assert "6.84" in ramp.summary and "8.12" in ramp.summary and "9.40" in ramp.summary
    assert ramp.note == ""


def test_a_colour_ramp_that_was_not_fetched_says_so_instead_of_drawing_colours(gent_ring):
    """Zonder het strookje van de dienst worden er geen kleuren verzonnen: de regel blijft staan
    met de drie hoogtes van de zone en zegt dat de schaal er niet is."""
    result = _result(gent_ring)
    result.relief = (6.84, 9.40, 8.12)

    report = rc.build_report(result, rc.ReportMeta(project="P1", author="A", company="C"))

    dtm = next(p for p in report.chapters[0].pages
               if isinstance(p, rc.MapPage) and p.map_id == "dhmv_dtm")
    assert dtm.ramp.image_path == ""
    assert "niet opgehaald" in dtm.ramp.note
    assert "6.84" in dtm.ramp.summary


def test_a_zone_without_measured_relief_gets_a_ramp_that_says_that(gent_ring):
    """Een dienst die plat lag en een vlakke zone laten allebei `relief` leeg. De regel onder de
    kaart mag dan geen hoogtes suggereren die niemand gemeten heeft."""
    report = rc.build_report(_result(gent_ring), rc.ReportMeta(project="P1", author="A", company="C"))

    dtm = next(p for p in report.chapters[0].pages
               if isinstance(p, rc.MapPage) and p.map_id == "dhmv_dtm")
    assert "geen hoogtewaarden" in dtm.ramp.summary


def test_only_the_maps_with_a_scale_for_a_legend_get_a_colour_ramp(gent_ring):
    """Een kleurbalk hoort bij een kaart waarvan de legenda een doorlopende schaal is - het
    hoogtemodel en de twee grondwaterstanden - en bij geen enkele andere."""
    report = rc.build_report(_result(gent_ring), rc.ReportMeta(project="P1", author="A", company="C"))

    with_ramp = [p.map_id for ch in report.chapters for p in ch.pages
                 if isinstance(p, rc.MapPage) and p.ramp is not None]
    assert with_ramp == ["dhmv_dtm", "gxg_ghg", "gxg_glg"]


# --- een kaart zonder beeld krijgt geen blad ---------------------------------------------------

def test_a_map_without_coverage_gets_no_sheet_but_stays_in_the_sources(gent_ring):
    """Een kaart zonder dekking krijgt geen blad maar staat wel in de bronnen.

    Een wit blad met een regel eronder is een blad dat de lezer omslaat. Dat de kaart wel degelijk
    geprobeerd is, hoort in het hoofdstuk Bronnen, met de reden erbij."""
    from desktopstudie.core.model import Provenance

    result = _result(gent_ring)
    result.provenance = [Provenance("Kaartbeeld Popp-kaart (1842-1879)",
                                    "https://geo.api.vlaanderen.be/HISTCART/wms",
                                    "2026-09-17T08:00:00", True, "geen dekking op deze locatie")]
    popp = next(p for p in rc.build_report(result, rc.ReportMeta(project="P", author="A", company="C"))
                .chapters[1].pages if isinstance(p, rc.MapPage) and p.map_id == "popp")

    report = rc.build_report(result, rc.ReportMeta(project="P", author="A", company="C"),
                             unavailable={rc.map_page_key(popp)})

    maps = [p.map_id for ch in report.chapters for p in ch.pages if isinstance(p, rc.MapPage)]
    assert "popp" not in maps and "ferraris" in maps
    sources = next(p for p in report.chapters[7].pages if p.title.startswith("Geraadpleegde"))
    assert sources.rows[0][3] == "ok - geen dekking op deze locatie"
    licences = next(p for p in report.chapters[7].pages if p.title.startswith("Kaartbronnen"))
    assert any("Popp" in row[0] for row in licences.rows), "de kaart blijft in de bronnenlijst staan"


def test_a_map_whose_image_failed_gets_no_sheet_but_stays_a_failed_source(gent_ring):
    """Een kaart waarvan het beeld mislukte krijgt geen blad maar staat wel als mislukte bron."""
    from desktopstudie.core.model import Provenance

    result = _result(gent_ring)
    result.provenance = [Provenance("Kaartbeeld Ferrariskaart (1777)",
                                    "https://geo.api.vlaanderen.be/HISTCART/wms",
                                    "2026-09-17T08:00:00", False,
                                    "kaartbeeld niet opgehaald; kaartpagina zonder ondergrond")]
    ferraris = next(p for p in rc.build_report(result, rc.ReportMeta(project="P", author="A", company="C"))
                    .chapters[1].pages if isinstance(p, rc.MapPage) and p.map_id == "ferraris")

    report = rc.build_report(result, rc.ReportMeta(project="P", author="A", company="C"),
                             unavailable={rc.map_page_key(ferraris)})

    maps = [p.map_id for ch in report.chapters for p in ch.pages if isinstance(p, rc.MapPage)]
    assert "ferraris" not in maps
    sources = next(p for p in report.chapters[7].pages if p.title.startswith("Geraadpleegde"))
    assert sources.rows[0][3].startswith("fout: kaartbeeld niet opgehaald")


def test_a_dropped_map_hands_its_zone_legend_back_to_a_sheet_of_its_own(gent_ring):
    """De legenda voor de zone komt uit de WFS, niet uit het kaartbeeld: valt het beeld weg, dan
    blijven die klassen waar. Ze staan dan weer op een eigen blad, want er is geen kaart meer om
    ze onder te zetten."""
    result = _result(gent_ring)
    bodemkaart = next(p for p in _geologie(result).pages
                      if isinstance(p, rc.MapPage) and p.map_id == "bodemkaart")

    geo = rc.build_report(result, rc.ReportMeta(project="P", author="A", company="C"),
                          unavailable={rc.map_page_key(bodemkaart)}).chapters[2]

    assert not [p for p in geo.pages if isinstance(p, rc.MapPage) and p.map_id == "bodemkaart"]
    legend = next(p for p in geo.pages if p.title == "Legenda voor de zone - Bodemkaart van Vlaanderen")
    assert legend.rows == [["OB", "OB", "Bebouwde zones", "-", "-", "Antropogeen"]]


def test_two_framings_of_one_map_are_dropped_apart(gent_ring):
    """Een kaart draagt meerdere kaders - de GRB-basiskaart drie - en een mozaiek kan het smalle
    kader wel dekken en het brede niet. De sleutel van een kaartpagina is dus de kaart plus haar
    kader, niet de kaart alleen."""
    report = rc.build_report(_result(gent_ring), rc.ReportMeta(project="P", author="A", company="C"))
    grb_pages = [p for ch in report.chapters for p in ch.pages
                 if isinstance(p, rc.MapPage) and p.map_id == "grb"]
    assert len(grb_pages) > 1
    keys = {rc.map_page_key(p) for p in grb_pages}
    assert len(keys) == len(grb_pages), "elk kader heeft een eigen sleutel"

    dropped = rc.build_report(_result(gent_ring), rc.ReportMeta(project="P", author="A", company="C"),
                              unavailable={rc.map_page_key(grb_pages[0])})

    left = [p for ch in dropped.chapters for p in ch.pages
            if isinstance(p, rc.MapPage) and p.map_id == "grb"]
    assert len(left) == len(grb_pages) - 1


# --- waar de virtuele boring genomen is --------------------------------------------------------

def test_the_virtual_borehole_chapter_says_where_the_borehole_was_taken(gent_ring):
    """Een virtuele boring is een punt, en de lezer hoort te zien welk punt: X en Y in Lambert 72
    en het maaiveld daar, per model - want twee modellen kunnen op een ander punt of op een ander
    maaiveld uitkomen."""
    result = _result(gent_ring)
    result.virtual_boreholes["g3dv3_F"] = VirtualBorehole(x=104326.4, y=192506.1, model="g3dv3_F", layers=[
        VbLayer("g3dv3_F_2", "Formatie van Gent", 8.38, 4.0, 4.38, "#FFFF00", "dekzand")])
    result.virtual_boreholes["hcovv2_S"] = VirtualBorehole(x=104326.4, y=192506.1, model="hcovv2_S", layers=[
        VbLayer("0100", "Quartair", 8.40, 2.0, 6.40, "#00FF00", "")])

    vb = rc.build_report(result, rc.ReportMeta(project="P", author="A", company="C")).chapters[3]

    place = next(p for p in vb.pages if isinstance(p, rc.TablePage) and p.title.startswith("Plaats"))
    assert place.columns == ["Model", "X (Lambert 72)", "Y (Lambert 72)", "Maaiveld (mTAW)", "Lagen"]
    assert place.rows == [["G3Dv3 - formaties", "104326.4", "192506.1", "8.38", "1"],
                          ["HCOV v2 - subeenheden", "104326.4", "192506.1", "8.40", "1"]]


def test_without_a_virtual_borehole_there_is_no_place_to_print(gent_ring):
    """Geen boring, geen punt: het hoofdstuk zegt dan dat de boring niet beschikbaar is en drukt
    geen tabel af met een plaats die niemand bevraagd heeft."""
    vb = rc.build_report(_result(gent_ring),
                         rc.ReportMeta(project="P", author="A", company="C")).chapters[3]

    assert not [p for p in vb.pages if isinstance(p, rc.TablePage)]


# --- de leeswijzer staat onder haar kaart -------------------------------------------------------

def test_the_reading_guide_stands_under_its_map_and_not_on_a_sheet_of_its_own(gent_ring):
    """Vier regels tekst op een verder leeg blad, elf keer in een rapport: dat is het wit waar de
    gebruiker over viel. De leeswijzer hoort onder het kaartkader, boven de legenda voor de zone."""
    geo = _geologie(_result(gent_ring))

    assert not [p for p in geo.pages if p.title.startswith("Leeswijzer")], \
        "de leeswijzer hoort geen eigen blad meer te zijn"
    bodemkaart = next(p for p in geo.pages if isinstance(p, rc.MapPage) and p.map_id == "bodemkaart")
    assert isinstance(bodemkaart.guide, rc.TextPage)
    assert bodemkaart.guide.title == "Leeswijzer - Bodemkaart van Vlaanderen"
    assert "Z zand" in bodemkaart.guide.html


def test_a_map_with_a_guide_but_no_zone_legend_carries_the_text_all_the_same(gent_ring):
    """Het hoogtemodel, HCOV en de Quartairkaart 1/200 000 hebben geen tabel met klassen onder hun
    kaart; hun leeswijzer hoort er toch te staan in plaats van op een blad ernaast."""
    report = rc.build_report(_result(gent_ring), rc.ReportMeta(project="P1", author="A", company="C"))

    dtm = next(p for p in report.chapters[0].pages
               if isinstance(p, rc.MapPage) and p.map_id == "dhmv_dtm")
    assert dtm.zone_legend is None
    assert isinstance(dtm.guide, rc.TextPage) and "meter TAW" in dtm.guide.html
    assert not [p for p in report.chapters[0].pages if p.title.startswith("Leeswijzer")]


def test_a_map_without_a_reading_guide_carries_none(gent_ring):
    """Een orthofoto heeft geen codes om uit te leggen en krijgt dus geen leeswijzer."""
    report = rc.build_report(_result(gent_ring), rc.ReportMeta(project="P1", author="A", company="C"))

    ferraris = next(p for p in report.chapters[1].pages
                    if isinstance(p, rc.MapPage) and p.map_id == "ferraris")
    assert ferraris.guide is None


def test_a_dropped_map_hands_back_its_guide_before_its_legend(gent_ring):
    """Valt het kaartbeeld weg, dan blijven de leeswijzer en de klassen in de zone staan - allebei
    op een eigen blad, in de volgorde waarin ze onder de kaart stonden."""
    result = _result(gent_ring)
    bodemkaart = next(p for p in _geologie(result).pages
                      if isinstance(p, rc.MapPage) and p.map_id == "bodemkaart")

    geo = rc.build_report(result, rc.ReportMeta(project="P", author="A", company="C"),
                          unavailable={rc.map_page_key(bodemkaart)}).chapters[2]

    titles = [p.title for p in geo.pages]
    guide = titles.index("Leeswijzer - Bodemkaart van Vlaanderen")
    legend = titles.index("Legenda voor de zone - Bodemkaart van Vlaanderen")
    assert guide < legend


def test_the_colour_ramp_marks_where_the_zone_lies_on_it(gent_ring):
    """Een balk van -50 tot 300 mTAW zegt over een bouwzone van vier meter niets: alles is een
    tint. De zone hoort er dus op gemarkeerd te staan, op de plaats waar haar laagste en hoogste
    hoogte vallen, met het gemiddelde als terugval voor een span dat te smal is om te tekenen."""
    result = _result(gent_ring)
    result.relief = (12.52, 16.25, 14.74)

    report = rc.build_report(result, rc.ReportMeta(project="P1", author="A", company="C"))

    ramp = next(p for p in report.chapters[0].pages
                if isinstance(p, rc.MapPage) and p.map_id == "dhmv_dtm").ramp
    # -50..300 is 350 m breed; 12,52 mTAW ligt dus op (12,52 + 50) / 350 van links.
    assert ramp.band == (pytest.approx(62.52 / 350.0), pytest.approx(66.25 / 350.0))
    assert ramp.band_label == "zone 12.52 - 16.25 mTAW"
    assert ramp.mean_at == pytest.approx(64.74 / 350.0)
    assert ramp.mean_label == "zone gemiddeld 14.74 mTAW"


def test_a_zone_outside_the_service_range_is_marked_on_the_strip_not_beside_it(gent_ring):
    """Een hoogte buiten het bereik van de dienst zou de markering van het papier af zetten; ze
    wordt op het uiteinde van de balk gelegd."""
    result = _result(gent_ring)
    result.relief = (-80.0, 400.0, 20.0)

    report = rc.build_report(result, rc.ReportMeta(project="P1", author="A", company="C"))

    ramp = next(p for p in report.chapters[0].pages
                if isinstance(p, rc.MapPage) and p.map_id == "dhmv_dtm").ramp
    assert ramp.band == (0.0, 1.0)


def test_a_ramp_without_measured_relief_has_nothing_to_mark(gent_ring):
    """Geen gemeten hoogtes, geen markering: een streepje op een balk zonder getal erachter zou
    een meting suggereren die er niet is."""
    report = rc.build_report(_result(gent_ring), rc.ReportMeta(project="P1", author="A", company="C"))

    ramp = next(p for p in report.chapters[0].pages
                if isinstance(p, rc.MapPage) and p.map_id == "dhmv_dtm").ramp
    assert ramp.band is None and ramp.mean_at is None


# --- geen uitgeschakelde kaart op een eigen blad, geen ontwikkelaarstaal -------------------------

def _all_text(report):
    """Elke tekst die een lezer in het rapport te zien krijgt, waar ze ook hangt."""
    out = []
    for chapter in report.chapters:
        out.append(chapter.title)
        pages = list(chapter.pages)
        for page in chapter.pages:
            if isinstance(page, rc.MapPage):
                pages += [part for part in (page.guide, page.zone_legend) if part is not None]
                if page.ramp is not None:
                    out += [page.ramp.title, page.ramp.low, page.ramp.high, page.ramp.summary,
                            page.ramp.note, page.ramp.band_label, page.ramp.mean_label]
        for page in pages:
            out.append(page.title)
            out.append(getattr(page, "note", ""))
            out.append(getattr(page, "html", ""))
            out.append(getattr(page, "caption", ""))
            out += list(getattr(page, "columns", []))
            for row in getattr(page, "rows", []):
                out += [str(cell) for cell in row]
            for entry in getattr(page, "entries", []):
                out += [entry.code, entry.sheet]
    return [text for text in out if text]


def test_a_disabled_map_gets_no_sheet_but_stands_in_the_sources(gent_ring):
    """Een uitgeschakelde kaart krijgt geen eigen blad maar staat wel in de bronnen.

    Een blad met een regel "Niet opgenomen" zegt tussen de historische kaarten niets wat de
    bronnenlijst niet beter zegt - daar hoort het thuis, met de reden erbij."""
    report = rc.build_report(_result(gent_ring), rc.ReportMeta(project="P", author="A", company="C"))

    hist = report.chapters[1]
    assert not [p for p in hist.pages if p.title.startswith("Historische topografische kaarten NGI")]
    assert not [p for p in hist.pages if p.title.startswith("Bommenkaart")]
    assert not any("Niet opgenomen" in getattr(p, "html", "") for p in hist.pages)

    left_out = next(p for p in report.chapters[7].pages if p.title.startswith("Niet opgenomen"))
    assert left_out.columns == ["Kaart", "Reden"]
    titles = [row[0] for row in left_out.rows]
    assert any("NGI" in title for title in titles) and any("ommenkaart" in title for title in titles)
    assert all(row[1] for row in left_out.rows), "elke regel hoort haar reden te noemen"


def test_no_report_text_addresses_the_developer(gent_ring):
    """Geen enkele rapporttekst richt zich tot de ontwikkelaar.

    "Vul wms_url in en zet enabled=True" is een opmerking voor wie de plugin schrijft; in het
    rapport van een klant heeft ze niets te zoeken."""
    report = rc.build_report(_with_quartair(_result(gent_ring)),
                             rc.ReportMeta(project="P", author="A", company="C"),
                             zone_legend_images=_profile_images("22026"))

    forbidden = ("wms_url", "wms_layer", "enabled", "=True", "=False", "None", "catalogus",
                 ".py", "TODO", "FIXME", "parameter")
    for text in _all_text(report):
        for word in forbidden:
            assert word not in text, f"ontwikkelaarstaal {word!r} in het rapport: {text!r}"


# --- de grondwaterstand onder haar eigen kaart --------------------------------------------------

def _with_gxg(result, value=2.85):
    """De GetFeatureInfo-rij zoals de dienst hem teruggeeft (live 2026-09-17)."""
    result.map_facts.append(MapFact("gxg_ghg", "Gemiddeld hoogste grondwaterstand (GHG)", [{
        "GHG-waarde_m-mv": value, "Standaardafwijking_GHG_m": 1.37,
        "Onderkant_80_procent_betrouwbaarheidsinterval_GHG_m-mv": 0.96,
        "Bovenkant_80_procent_betrouwbaarheidsinterval_GHG_m-mv": 4.74}]))
    return result


def test_the_groundwater_map_carries_its_value_and_its_colour_bar(gent_ring):
    """De GHG-kaart droeg geen getal en geen legenda. Nu staat de gemeten waarde in de tabel onder
    de kaart en de kleurbalk van de dienst eronder, met haar klassegrenzen erbij."""
    result = _with_gxg(_result(gent_ring))
    result.relief = (12.52, 16.25, 14.74)

    geo = _geologie(result, zone_legend_images={rc.ramp_image_key("gxg_ghg"):
                                                "legendas/gxg_ghg_schaal.png"})

    ghg = next(p for p in geo.pages if isinstance(p, rc.MapPage) and p.map_id == "gxg_ghg")
    table = ghg.zone_legend
    assert table.columns[0] == "GHG (m onder maaiveld)"
    assert table.rows[0][0] == "2.85"
    ramp = ghg.ramp
    assert ramp.image_path == "legendas/gxg_ghg_schaal.png"
    assert [label for _at, label in ramp.ticks] == ["0", "1", "2", "3", "4", "5", "10", "15", "20"]
    assert ramp.ticks[0][0] == 0.0 and ramp.ticks[-1][0] == 1.0


def test_the_groundwater_depth_is_also_given_as_a_level(gent_ring):
    """Een diepte onder het maaiveld zegt een funderingsontwerper minder dan een peil. De regel
    onder de balk rekent om met het gemeten maaiveld en noemt die aanname."""
    result = _with_gxg(_result(gent_ring))
    result.relief = (12.52, 16.25, 14.74)

    geo = _geologie(result)

    ramp = next(p for p in geo.pages if isinstance(p, rc.MapPage) and p.map_id == "gxg_ghg").ramp
    assert "2.85 m onder maaiveld" in ramp.summary
    assert "11.89 mTAW" in ramp.summary
    assert "gemiddelde maaiveld" in ramp.summary, "de aanname hoort erbij te staan"


def test_without_a_measured_ground_level_the_depth_is_not_converted(gent_ring):
    """Zonder gemeten maaiveld wordt er niets omgerekend: een peil uit een verzonnen maaiveld is
    een getal dat niemand kan narekenen."""
    geo = _geologie(_with_gxg(_result(gent_ring)))

    ramp = next(p for p in geo.pages if isinstance(p, rc.MapPage) and p.map_id == "gxg_ghg").ramp
    assert "2.85 m onder maaiveld" in ramp.summary
    assert "mTAW" not in ramp.summary


def test_a_groundwater_point_the_service_knows_nothing_about_says_so(gent_ring):
    """Buiten het model antwoordt de dienst met niets; de balk blijft, de regel zegt dat er geen
    waarde is in plaats van een nul te suggereren."""
    result = _result(gent_ring)
    result.map_facts.append(MapFact("gxg_ghg", "Gemiddeld hoogste grondwaterstand (GHG)", []))

    geo = _geologie(result)

    ramp = next(p for p in geo.pages if isinstance(p, rc.MapPage) and p.map_id == "gxg_ghg").ramp
    assert "geen waarde" in ramp.summary and "2.85" not in ramp.summary


def test_a_measured_number_is_printed_to_two_decimals(gent_ring):
    """De dienst antwoordt met een dubbele-precisiegetal: 2.8499999046325684 m. Zo'n rij in een
    rapport is onleesbaar en suggereert een nauwkeurigheid die er niet is - twee decimalen is wat
    een grondwaterstand waard is."""
    result = _with_gxg(_result(gent_ring), value=2.8499999046325684)

    geo = _geologie(result)

    table = next(p for p in geo.pages
                 if isinstance(p, rc.MapPage) and p.map_id == "gxg_ghg").zone_legend
    assert table.rows[0][0] == "2.85"
    assert table.rows[0][1] == "1.37"


def test_a_continuous_map_prints_the_representative_point_not_nine_samples(gent_ring):
    """Een kaart met een doorlopende waarde heeft geen "klassen in de zone": elk bevraagd punt
    geeft zijn eigen getal, en negen bijna gelijke rijen kosten twee bladen en zeggen niets extra.
    De tabel toont het representatieve punt - het punt waar de virtuele boring ook staat."""
    result = _result(gent_ring)
    rows = [{"GHG-waarde_m-mv": value, "Standaardafwijking_GHG_m": 1.37,
             "Onderkant_80_procent_betrouwbaarheidsinterval_GHG_m-mv": 0.96,
             "Bovenkant_80_procent_betrouwbaarheidsinterval_GHG_m-mv": 4.74}
            for value in (2.85, 2.88, 2.95, 2.94, 2.69, 2.65, 2.91, 3.0)]
    result.map_facts.append(MapFact("gxg_ghg", "Gemiddeld hoogste grondwaterstand (GHG)", rows))

    geo = _geologie(result)

    table = next(p for p in geo.pages
                 if isinstance(p, rc.MapPage) and p.map_id == "gxg_ghg").zone_legend
    assert len(table.rows) == 1
    assert table.rows[0][0] == "2.85", "de eerste bevraging is het representatieve punt"
    assert "representatieve punt" in table.title


# --- waarom deze sonderingen een figuur kregen, en wat de boringen vermelden --------------------

def test_the_chapter_says_why_an_electrical_sounding_was_chosen(gent_ring):
    """Een lezer die een elektrische sondering van 300 m ziet afgebeeld en een mechanische van
    40 m niet, hoort te weten waarom."""
    from desktopstudie.core.model import Cpt

    result = _result(gent_ring)
    result.cpts.append(Cpt("e1", "E-1", 104000.0, 192000.0, 8.0, 20.0, "2020-01-01",
                           "continu elektrisch", "E", None, None,
                           "https://www.dov.vlaanderen.be/data/sondering/e1", 300.0))
    result.figures["cpt_e1"] = "figuren/cpt_e1.png"

    inv = rc.build_report(result, rc.ReportMeta(project="P", author="A", company="C")).chapters[4]

    texts = " ".join(getattr(p, "html", "") + p.title for p in inv.pages)
    assert "elektrische" in texts and "figuur" in texts


def test_a_borehole_description_with_something_notable_says_so_under_its_figure(gent_ring):
    """Een korte "Opmerkingen"-regel onder de boring: wat de beschrijving vermeldt en op welke
    diepte, in de woorden van de beschrijving zelf."""
    from desktopstudie.core.model import Borehole, LithologyLayer

    result = _result(gent_ring)
    result.boreholes.append(Borehole("b1", "kb22-B1", 104000.0, 192000.0, 8.0, 10.0, "1970-01-01",
                                     "spoelboring", "geologie", None,
                                     "https://www.dov.vlaanderen.be/data/boring/b1", 80.0,
                                     lithology=[
                                         LithologyLayer(0.0, 0.2, "Straatsteen"),
                                         LithologyLayer(2.6, 4.2, "veenhoudende leem")]))
    result.figures["boring_b1"] = "figuren/boring_b1.png"

    inv = rc.build_report(result, rc.ReportMeta(project="P", author="A", company="C")).chapters[4]

    figure = next(p for p in inv.pages if isinstance(p, rc.FigurePage) and "kb22-B1" in p.title)
    assert "Opmerkingen" in figure.caption
    assert "straatsteen (0.00-0.20 m)" in figure.caption
    assert "veenhoudende (2.60-4.20 m)" in figure.caption


def test_a_plain_borehole_gets_no_remarks_line(gent_ring):
    """Een gewone zandbeschrijving levert geen opmerking op; anders staat er onder elke boring een
    regel die niets zegt."""
    from desktopstudie.core.model import Borehole, LithologyLayer

    result = _result(gent_ring)
    result.boreholes.append(Borehole("b2", "kb22-B2", 104000.0, 192000.0, 8.0, 10.0, "1970-01-01",
                                     "spoelboring", "geologie", None,
                                     "https://www.dov.vlaanderen.be/data/boring/b2", 80.0,
                                     lithology=[LithologyLayer(0.0, 2.0, "matig fijn zand")]))
    result.figures["boring_b2"] = "figuren/boring_b2.png"

    inv = rc.build_report(result, rc.ReportMeta(project="P", author="A", company="C")).chapters[4]

    figure = next(p for p in inv.pages if isinstance(p, rc.FigurePage) and "kb22-B2" in p.title)
    assert "Opmerkingen" not in figure.caption
