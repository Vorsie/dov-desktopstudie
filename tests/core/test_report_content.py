from __future__ import annotations

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
    assert isinstance(geo.pages[1], rc.TextPage) and geo.pages[1].title.startswith("Leeswijzer")
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
    report = rc.build_report(_result(gent_ring), rc.ReportMeta(project="P1", author="A", company="C"))
    hist = report.chapters[1]
    texts = [p for p in hist.pages if isinstance(p, rc.TextPage)]
    slot = next(p for p in texts if p.title.startswith("Bommenkaart"))
    assert "geen open data" in slot.html and "explosieven" in slot.html
    assert not any(isinstance(p, rc.MapPage) and p.map_id == "bommenkaart" for p in hist.pages)
    manual = next(p for p in texts if p.title.startswith("Manuele controle"))
    assert "conventionele en toxische explosieven" in manual.html
    assert "bommenkaart.be" in manual.html and "DOVO" in manual.html


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


def test_the_reading_guide_stands_right_behind_its_map(gent_ring):
    """De volgorde waarin de lezer het nodig heeft: eerst de kaart met de klassen die in de zone
    liggen eronder, dan hoe die codes te lezen zijn (de leeswijzer)."""
    geo = _geologie(_result(gent_ring))

    titles = [p.title for p in geo.pages]
    guide = titles.index("Leeswijzer - Bodemkaart van Vlaanderen")
    assert titles.index("Bodemkaart van Vlaanderen") == guide - 1
    page = geo.pages[guide]
    assert isinstance(page, rc.TextPage)
    assert "Z zand" in page.html and "drainage" in page.html
    assert '<a href="https://www.dov.vlaanderen.be/page/' in page.html, "de link hoort klikbaar te zijn"


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
                        "Leeswijzer - Quartairgeologische kaart 1/50 000 (samengesteld)",
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
    uitleg. De leeswijzer staat dan direct achter de kaartpagina."""
    report = rc.build_report(_result(gent_ring), rc.ReportMeta(project="P1", author="A", company="C"))

    titles = [p.title for p in report.chapters[0].pages]
    dtm = titles.index("Digitaal Hoogtemodel Vlaanderen II - DTM 1 m")
    assert titles[dtm + 1] == "Leeswijzer - Digitaal Hoogtemodel Vlaanderen II - DTM 1 m"
    assert "Leeswijzer - Ferrariskaart (1777)" not in [p.title for p in report.chapters[1].pages]


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
