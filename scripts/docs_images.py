"""Build the images the README shows: sheets from a rendered report, two stills of the plugin in
QGIS, and the demo GIF of a run.

  python scripts/docs_images.py --paginas uitvoer/gent19/paginas --frames uitvoer/demo_frames

The sheets come from a real study rendered with `--paginas` (run_headless.py) - SHEETS says which
page is which and why it is in the README. The stills and the GIF come from a smoke run that
captured its own window: `DESKTOPSTUDIE_FRAMES=<folder> ... --code scripts/smoke_plugin.py`.

Everything is written to docs/afbeeldingen/. A repository is not an image host, so each image is
scaled down and quantised to a palette before it is saved; the GIF gets one shared palette for
all its frames, which keeps the frame-to-frame differences (and the file) small.

Pillow only - it rides along with matplotlib, which the core already needs. No new dependency.
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import List

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "docs" / "afbeeldingen"

# page in the report -> file name in docs/afbeeldingen. Five sheets, each a different capability:
# a historical map, a coded map with its reading guide, a colour ramp with the value it belongs to,
# the survey data DOV holds around the zone, and what the study flags out of all that.
SHEETS = {
    9: "rapport-buurtwegen.jpg",
    19: "rapport-isopachen.jpg",
    23: "rapport-ghg.jpg",
    34: "rapport-grondonderzoek.jpg",
    55: "rapport-signaleringen.png",
}
SHEET_WIDTH = 1100
STILL_WIDTH = 1100
JPEG_QUALITY = 82
GIF_WIDTH = 1000
GIF_FRAMES = 16
GIF_MS = 1100
GIF_LAST_MS = 2600
GIF_COLOURS = 128
STILL_DIALOG = 6  # the frame where the geocoder has answered and the first phase is running
STILL_LAYERS = -1  # the last frame: layers in the tree, the zone on the canvas, the PDF announced


def _page_file(folder: Path, page: int) -> Path:
    """Page 1 has no number in its name; the rest are pagina_<n>.png."""
    return folder / ("pagina.png" if page == 1 else f"pagina_{page}.png")


def _scaled(image: Image.Image, width: int) -> Image.Image:
    image = image.convert("RGB")
    if image.width <= width:
        return image
    return image.resize((width, round(image.height * width / image.width)), Image.LANCZOS)


def _save(image: Image.Image, target: Path, colours: int = 256) -> None:
    """JPEG for a sheet that is mostly map, PNG for one that is mostly text: a scanned map or a
    dense basemap compresses like a photograph, a table of black letters on white does not (and
    picks up visible ringing). The suffix in SHEETS decides, so the file names stay stable."""
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.suffix.lower() in (".jpg", ".jpeg"):
        image.save(target, quality=JPEG_QUALITY, optimize=True, progressive=True)
    else:
        image.quantize(colors=colours, method=Image.MEDIANCUT, dither=Image.FLOYDSTEINBERG).save(
            target, optimize=True)
    print(f"{target.relative_to(ROOT)}  {target.stat().st_size / 1024:.0f} kB  {image.width}x{image.height}")


def sheets(folder: Path, out_dir: Path) -> None:
    for page, name in sorted(SHEETS.items()):
        source = _page_file(folder, page)
        if not source.exists():
            print(f"overgeslagen, bestaat niet: {source}")
            continue
        _save(_scaled(Image.open(source), SHEET_WIDTH), out_dir / name)


def _frames(folder: Path) -> List[Path]:
    return sorted(folder.glob("frame_*.png"))


def stills(folder: Path, out_dir: Path) -> None:
    frames = _frames(folder)
    if not frames:
        print(f"geen beelden in {folder}")
        return
    for index, name in ((STILL_DIALOG, "plugin-dialoog.png"), (STILL_LAYERS, "qgis-lagen.png")):
        _save(_scaled(Image.open(frames[index]), STILL_WIDTH), out_dir / name)


def gif(folder: Path, target: Path, count: int = GIF_FRAMES, ms: int = GIF_MS) -> None:
    frames = _frames(folder)
    if not frames:
        print(f"geen beelden in {folder}")
        return
    # Evenly spread, first and last always in: the first shows the filled dialog, the last the
    # finished study, and those two are the whole point of the demo.
    step = max(1, (len(frames) - 1) / max(1, count - 1))
    picked = sorted({round(i * step) for i in range(count)} | {0, len(frames) - 1})
    images = [_scaled(Image.open(frames[i]), GIF_WIDTH) for i in picked if i < len(frames)]
    palette = images[-1].quantize(colors=GIF_COLOURS, method=Image.MEDIANCUT)
    quantised = [image.quantize(palette=palette, dither=Image.NONE) for image in images]
    durations = [ms] * len(quantised)
    durations[-1] = GIF_LAST_MS
    target.parent.mkdir(parents=True, exist_ok=True)
    quantised[0].save(target, save_all=True, append_images=quantised[1:], duration=durations,
                      loop=0, optimize=True)
    seconds = sum(durations) / 1000
    print(f"{target.relative_to(ROOT)}  {target.stat().st_size / 1024:.0f} kB  "
          f"{len(quantised)} beelden  {seconds:.0f} s")


def main(argv: List[str] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--paginas", type=Path, help="map met pagina*.png van een gerenderde studie")
    parser.add_argument("--frames", type=Path, help="map met frame_*.png van een vastgelegde run")
    parser.add_argument("--uit", type=Path, default=OUT_DIR)
    parser.add_argument("--aantal", type=int, default=GIF_FRAMES, help="beelden in de GIF")
    parser.add_argument("--ms", type=int, default=GIF_MS, help="tijd per beeld in de GIF")
    args = parser.parse_args(argv)
    if not args.paginas and not args.frames:
        parser.error("geef --paginas, --frames of allebei")
    if args.paginas:
        sheets(args.paginas, args.uit)
    if args.frames:
        stills(args.frames, args.uit)
        gif(args.frames, args.uit / "demo.gif", count=args.aantal, ms=args.ms)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
