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
