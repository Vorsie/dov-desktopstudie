"""Ad-hoc script: render the headline figures from recorded fixtures for a visual check. Not
part of the test suite.

Run:  python scripts/render_figures.py
Writes uitvoer/figuren_check/*.png (git-ignored)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from desktopstudie.core.figures import borehole_column, cpt_figure, section_figure, vb_column  # noqa: E402
from desktopstudie.core.model import (Borehole, Cpt, LithologyLayer, ProjectedPoint, Section,  # noqa: E402
                                      VirtualBorehole)
from desktopstudie.core.services.dov_xml import parse_cpt_profile  # noqa: E402
from desktopstudie.core.services.virtuele_boring import parse_doorprik  # noqa: E402
from tests.core.conftest import fixture_bytes, fixture_json  # noqa: E402

OUT = ROOT / "uitvoer" / "figuren_check"
OUT.mkdir(parents=True, exist_ok=True)

modern = Cpt("2024-090319", "S407", 0, 0, 8.0, 32.2, "2024-04-05", "continu elektrisch", None, None, None, "", 12.0,
             profile=parse_cpt_profile(fixture_bytes("sondering_2024-090319.xml")))
old = Cpt("1965-039716", "SIX", 0, 0, 6.26, 20.4, "1965-02-17", "discontinu mechanisch", "M4", None, None, "", 210.0,
          profile=parse_cpt_profile(fixture_bytes("sondering_1965-039716.xml")))
cpt_figure.plot_cpt(modern, OUT / "cpt_modern.png")
cpt_figure.plot_cpt(old, OUT / "cpt_old.png")

bh = Borehole("k", "B938", 0, 0, 7.0, 48.0, None, None, None, None, "", 100.0, lithology=[
    LithologyLayer(0.0, 1.2, "bruin fijn zand"), LithologyLayer(1.2, 6.0, "grijze klei"),
    LithologyLayer(6.0, 48.0, "groen zand")])
borehole_column.plot_borehole(bh, OUT / "borehole.png")

vb = parse_doorprik(fixture_json("vb_g3dv3_F.json"), 104326.0, 192506.0, "g3dv3_F")
vb_column.plot_virtual_borehole(vb, OUT / "vb.png")

sec = Section(line=((104126.0, 192506.0), (104526.0, 192506.0)),
              boreholes=[VirtualBorehole(104126.0 + 100 * i, 192506.0, "g3dv3_F", vb.layers) for i in range(5)],
              projected=[ProjectedPoint("cpt", "S407", 200.0, 5.0, 14.0, 32.0),
                         ProjectedPoint("boring", "B1", 250.0, -3.0, None, 10.0)],
              zone_from_m=100.0, zone_to_m=300.0)
section_figure.plot_section(sec, OUT / "section.png", max_depth_m=60.0)

# Section D critical fix, viewed directly: columns and projected points must line up at their
# TRUE chainage (not index * spacing), including with missing boreholes.
base_x, y0 = 104000.0, 192506.0
chainages = [i * 40.0 for i in range(11) if i not in (3, 7)]
sec2 = Section(line=((base_x, y0), (base_x + 400.0, y0)),
               boreholes=[VirtualBorehole(base_x + c, y0, "g3dv3_F", vb.layers) for c in chainages],
               projected=[ProjectedPoint("cpt", "S407", 200.0, 5.0, 14.0, 32.0)],
               zone_from_m=100.0, zone_to_m=300.0, failed_points=2)
section_figure.plot_section(sec2, OUT / "section_chainage.png", max_depth_m=60.0)

# 27 alternating thin/thick layers, cycling through every lithology keyword, to check that
# draw_depth_column's collision avoidance keeps 27 labels readable and non-overlapping.
words = ["zand", "klei", "leem", "silt", "grind", "veen", "steen"]
layers = []
top = 0.0
for i in range(27):
    thickness = 0.3 if i % 2 == 0 else 1.9
    base = top + thickness
    layers.append(LithologyLayer(top, base, f"{words[i % len(words)]} laag {i}"))
    top = base
bh27 = Borehole("k", "B-MANY", 0, 0, None, top, None, None, None, None, "", 50.0, lithology=layers)
borehole_column.plot_borehole(bh27, OUT / "borehole_27layers.png")

print("wrote", sorted(p.name for p in OUT.glob("*.png")))

# Task 11b, viewed directly: the section built from the DOV profile endpoint. Live where possible
# (fine, contiguous columns at max(5, length/40) = 10 m), falling back to the 100 m fixture.
from desktopstudie.core.logging_util import Log  # noqa: E402
from desktopstudie.core.model import StudyZone  # noqa: E402
from desktopstudie.core.section import build_section  # noqa: E402
from desktopstudie.core.services.http import HttpClient  # noqa: E402
from desktopstudie.core.services.virtuele_boring import parse_profile  # noqa: E402

GENT_RING = [(104226.0, 192406.0), (104426.0, 192406.0), (104426.0, 192606.0), (104226.0, 192606.0)]
GENT_LINE = ((104126.0, 192506.0), (104526.0, 192506.0))
# Sloping line in the Flemish Ardennes, so the surface line and the dashed anchors are visible.
HILL_LINE = ((89500.0, 181500.0), (90300.0, 182300.0))
HILL_RING = [(89800.0, 181800.0), (90000.0, 181800.0), (90000.0, 182000.0), (89800.0, 182000.0)]

try:
    client = HttpClient(log=Log("render"))
    live = build_section(client, GENT_LINE, StudyZone(ring=GENT_RING, name="Gent"),
                         [Cpt("k", "S407", 104326.0, 192520.0, 14.0, 32.0, None, None, None, None, None, "", 0.0)],
                         [], [], n_points=5, corridor_m=50.0, model="g3dv3_F", log=Log("render"))
    section_figure.plot_section(live, OUT / "section_profile.png", max_depth_m=60.0)
    hill = build_section(client, HILL_LINE, StudyZone(ring=HILL_RING, name="Ronse"), [], [], [],
                         n_points=5, corridor_m=50.0, model="g3dv3_F", log=Log("render"))
    section_figure.plot_section(hill, OUT / "section_profile_hill.png", max_depth_m=60.0)
    print("live profile:", live.profile.resolution_m, "m ->", len(live.profile.columns), "columns;",
          "hill:", hill.profile.resolution_m, "m ->", len(hill.profile.columns), "columns")
except Exception as exc:  # offline: fall back to the recorded 100 m fixture
    print("live profile unavailable, using the fixture:", exc)
    anchor_order = [layer.code for layer in vb.layers]
    profile = parse_profile(fixture_json("vb_profile_g3dv3_F.json"), "g3dv3_F", anchor_order,
                            lambda along: 14.62, 100.0)
    sec3 = Section(line=GENT_LINE,
                   boreholes=[VirtualBorehole(104126.0 + 200 * i, 192506.0, "g3dv3_F", vb.layers) for i in range(3)],
                   projected=[ProjectedPoint("cpt", "S407", 200.0, 5.0, 14.0, 32.0)],
                   zone_from_m=100.0, zone_to_m=300.0, profile=profile)
    section_figure.plot_section(sec3, OUT / "section_profile.png", max_depth_m=60.0)

print("wrote", sorted(p.name for p in OUT.glob("*.png")))
