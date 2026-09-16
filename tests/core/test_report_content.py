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
    # chapter 3 interleaves: each map page is directly followed by its own fact table
    assert isinstance(geo.pages[0], rc.MapPage) and geo.pages[0].map_id == "bodemkaart"
    assert isinstance(geo.pages[1], rc.TablePage) and geo.pages[1].title.startswith("Bodemkaart")
    tables = [p for p in geo.pages if isinstance(p, rc.TablePage)]
    assert tables[0].title.startswith("Bodemkaart") and tables[0].rows[0][0] == "OB"
    assert tables[0].columns[2] == "Omschrijving"  # readable header, not the raw DOV field name
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


def test_the_new_geology_maps_get_a_map_page_and_a_fact_table(gent_ring):
    report = rc.build_report(_result(gent_ring), rc.ReportMeta(project="P1", author="A", company="C"))
    geo = report.chapters[2]
    map_ids = [p.map_id for p in geo.pages if isinstance(p, rc.MapPage)]
    assert {"grondverschuiving_gevoeligheid", "grondverschuiving_gekarteerd", "pfas_no_regret"} <= set(map_ids)
    pfas = next(p for p in geo.pages if isinstance(p, rc.TablePage) and p.title.startswith("PFAS"))
    assert pfas.columns == ["PFAS-dossier", "Gemeente", "Straat", "Status", "Geldig vanaf", "Maatregelen (link)"]


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


QUARTAIR_LEGEND = ("https://datasets.omgeving.vlaanderen.be/be.vlaanderen.omgeving.distribution.geo."
                   "e58c3358-e149-42b6-9229-c3a9ac88c3d4.DOV_Quartair_50000_{code}_png")


def _with_quartair(result, codes=("22026", "22010", "22026", "22098")):
    """De quartairrijen zoals de WFS ze levert: een rij per kaartvlak, dus hetzelfde profieltype
    kan twee keer in de zone liggen. De eerste twee cijfers van de code zijn het kaartblad."""
    result.map_facts.append(MapFact("quartair", "Quartairgeologische kaart 1/50 000 (samengesteld)", [
        {"profieltype": code, "legende": QUARTAIR_LEGEND.format(code=code)} for code in codes]))
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


def test_the_zone_legend_lists_only_the_classes_that_lie_in_the_zone(gent_ring):
    """De volledige bodemlegende telt honderden series; de lezer heeft er een nodig. "Legenda voor
    de zone" zet de klassen die in deze zone voorkomen op een rij, met hun omschrijving erbij."""
    geo = _geologie(_result(gent_ring))

    legend = next(p for p in geo.pages if p.title == "Legenda voor de zone - Bodemkaart van Vlaanderen")
    assert legend.columns == ["Bodemtype", "Serie", "Omschrijving", "Textuur", "Drainage"]
    assert legend.rows == [["OB", "OB", "Bebouwde zones", "-", "-"]]


def test_the_reading_guide_stands_between_the_facts_and_the_zone_legend(gent_ring):
    """De volgorde waarin de lezer het nodig heeft: eerst wat er ligt (de feitentabel), dan hoe die
    codes te lezen zijn (de leeswijzer), dan de legenda van de klassen in de zone."""
    geo = _geologie(_result(gent_ring))

    titles = [p.title for p in geo.pages]
    facts = titles.index("Bodemkaart van Vlaanderen - eenheden in de zone")
    guide = titles.index("Leeswijzer - Bodemkaart van Vlaanderen")
    legend = titles.index("Legenda voor de zone - Bodemkaart van Vlaanderen")
    assert facts < guide < legend
    page = geo.pages[guide]
    assert isinstance(page, rc.TextPage)
    assert "Z zand" in page.html and "drainage" in page.html
    assert '<a href="https://www.dov.vlaanderen.be/page/' in page.html, "de link hoort klikbaar te zijn"


def test_the_quartair_zone_legend_names_the_sheet_and_points_at_the_drawing(gent_ring):
    """Twee kaartvlakken van hetzelfde profieltype zijn een legenda-eenheid: de legenda telt
    profieltypes, geen kaartvlakken. En een URL van 145 tekens zegt een lezer niets - de tekening
    zelf staat erachter, dus de tabel verwijst ernaar en noemt het kaartblad waarop dat type is
    gekarteerd."""
    geo = _geologie(_with_quartair(_result(gent_ring)))

    legend = next(p for p in geo.pages if p.title.startswith("Legenda voor de zone - Quartair"))
    assert legend.columns == ["Profieltype", "Kaartblad", "Omschrijving"]
    assert legend.rows == [["22026", "22", "zie profieltekening hierna"],
                           ["22010", "22", "zie profieltekening hierna"],
                           ["22098", "22", "zie profieltekening hierna"]]
    assert not any("http" in cell for row in legend.rows for cell in row), legend.rows


def test_every_profile_type_gets_its_header_and_the_sheet_its_units_once(gent_ring):
    """De tekening van DOV bestaat uit twee delen: bovenaan het profieltype zelf (kleurvlak, code
    en een regel uitleg) en daaronder de eenhedentabel van het kaartblad, die voor elk profieltype
    van dat blad dezelfde is. Dus een kopstrook per profieltype, en de eenhedentabel een keer."""
    result = _with_quartair(_result(gent_ring))

    geo = _geologie(result, zone_legend_images=_profile_images("22026", "22010", "22098"))

    figures = [p for p in geo.pages if isinstance(p, rc.FigurePage)]
    assert [(f.title, f.image_path) for f in figures] == [
        ("Profieltype 22026", "legendas/quartair_22026_kop.png"),
        ("Profieltype 22010", "legendas/quartair_22010_kop.png"),
        ("Profieltype 22098", "legendas/quartair_22098_kop.png"),
        ("Eenheden op kaartblad 22", "legendas/quartair_kaartblad_22.png")]
    titles = [p.title for p in geo.pages]
    assert titles.index("Legenda voor de zone - Quartairgeologische kaart 1/50 000 (samengesteld)") < \
        titles.index("Profieltype 22026")


def test_a_header_strip_is_drawn_at_its_own_size_and_the_units_table_fills_the_page(gent_ring):
    """De kopstrook is een reepje van enkele centimeters hoog: over een blad uitgerekt wordt ze een
    wazige banner. De eenhedentabel is wel een volle tekening en mag het blad vullen."""
    geo = _geologie(_with_quartair(_result(gent_ring)),
                    zone_legend_images=_profile_images("22026", "22010", "22098"))

    figures = {p.title: p for p in geo.pages if isinstance(p, rc.FigurePage)}
    assert figures["Profieltype 22026"].fit == "natural"
    assert figures["Eenheden op kaartblad 22"].fit == "zoom"
    assert rc.FigurePage("t", "p").fit == "zoom", "zoom blijft de standaard voor elke andere figuur"


def test_a_profile_type_without_a_drawing_gets_no_page(gent_ring):
    """De kern haalt niets op. Kreeg ze geen pad voor een profieltype, dan staat er niets - geen
    belofte van een tekening die er niet is."""
    result = _with_quartair(_result(gent_ring))

    geo = _geologie(result, zone_legend_images=_profile_images("22026"))

    titles = [p.title for p in geo.pages]
    assert "Profieltype 22026" in titles
    assert "Profieltype 22010" not in titles and "Profieltype 22098" not in titles
    assert "Eenheden op kaartblad 22" in titles
    assert not any(p.title.startswith("Profieltype") for p in _geologie(result).pages)


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

    empty = next(p for p in geo.pages if p.title.startswith("Legenda voor de zone - Tertiair"))
    assert empty.rows == [] and empty.note == "Geen kaarteenheden binnen de zone."
    silent = next(p for p in geo.pages if p.title.startswith("Legenda voor de zone - HCOV"))
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

    legend = next(p for p in geo.pages if p.title.startswith("Legenda voor de zone - PFAS"))
    link = legend.rows[0][-1]
    assert link.startswith("https://www.vlaanderen.be/...") and len(link) < 80, link


def test_a_fact_table_prints_a_link_in_its_short_form_too(gent_ring):
    """Dezelfde regel als in de legenda voor de zone, en om dezelfde reden: de feitentabel van het
    Quartair kapte de tekening-URL af op "...DOV_Quartair_5000", midden in een woord. Wat de dienst
    stuurde blijft in `MapFact.rows` en in studie.json staan; op papier staat de korte vorm."""
    geo = _geologie(_with_quartair(_result(gent_ring)))

    facts = next(p for p in geo.pages if p.title.endswith("eenheden in de zone")
                 and p.title.startswith("Quartairgeologische kaart 1/50"))
    links = [row[1] for row in facts.rows]
    assert all(link.startswith("https://datasets.omgeving.vlaanderen.be/...") for link in links), links
    assert all(len(link) < 80 for link in links), links
    assert links[0].endswith("DOV_Quartair_50000_22026_png")
