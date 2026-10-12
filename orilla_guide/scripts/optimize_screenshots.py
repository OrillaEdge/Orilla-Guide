"""Generate lossless WebP screenshots and update the guide's image references.

Run with Python and Pillow installed: python scripts/optimize_screenshots.py
Original PNGs remain untouched. Full-size WebP files preserve every pixel;
previews fit within 1600 pixels for the guide's 760-pixel content column.
"""

import json
import re
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parent.parent
HTML = ROOT / "index.html"
OUTPUT = ROOT / "images" / "optimized"
IMAGE_TAG = re.compile(r"<img\b[^>]*>")


def original_path(tag):
    match = re.search(r'(?<![\w-])src="(images/[^\"]+)"', tag)
    if not match:
        return None
    name = Path(match.group(1)).name
    if name.endswith(".preview.webp"):
        name = name.removesuffix(".preview.webp") + ".png"
    elif name.endswith(".webp"):
        name = name.removesuffix(".webp") + ".png"
    return "images/" + name


def main():
    originals = sorted(
        {path for tag in IMAGE_TAG.findall(HTML.read_text(encoding="utf-8"))
         if (path := original_path(tag))}
    )
    OUTPUT.mkdir(exist_ok=True)
    manifest = {}
    for path in originals:
        source = ROOT / path
        full = OUTPUT / (source.stem + ".webp")
        with Image.open(source) as image:
            mode = "RGBA" if "A" in image.getbands() else "RGB"
            pixels = image.convert(mode)
            pixels.save(full, "WEBP", lossless=True, exact=True, method=6)
            with Image.open(full) as decoded:
                if decoded.convert(mode).tobytes() != pixels.tobytes():
                    raise ValueError(f"Full-size screenshot changed pixels: {path}")

            preview = pixels.copy()
            preview.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
            preview_path = full
            if preview.size != pixels.size:
                preview_path = OUTPUT / (source.stem + ".preview.webp")
                preview.save(preview_path, "WEBP", lossless=True, exact=True, method=6)
            manifest[path] = {
                "preview": preview_path.relative_to(ROOT).as_posix(),
                "full": full.relative_to(ROOT).as_posix(),
                "width": preview.width,
                "height": preview.height,
                "fullWidth": pixels.width,
                "fullHeight": pixels.height,
                "originalBytes": source.stat().st_size,
                "previewBytes": preview_path.stat().st_size,
                "fullBytes": full.stat().st_size,
            }

    def update_tag(match):
        tag = match.group(0)
        path = original_path(tag)
        if path not in manifest:
            return tag
        entry = manifest[path]
        attributes = {
            "src": entry["preview"],
            "width": entry["width"],
            "height": entry["height"],
            "data-full-src": entry["full"],
            "data-full-width": entry["fullWidth"],
            "data-full-height": entry["fullHeight"],
            "decoding": "async",
        }
        for name, value in attributes.items():
            pattern = re.compile(r'(?<![\w-])' + re.escape(name) + r'="[^\"]*"')
            attribute = f'{name}="{value}"'
            if pattern.search(tag):
                tag = pattern.sub(lambda _: attribute, tag)
            else:
                tag = tag.replace("<img", "<img " + attribute, 1)
        return tag

    # Read again so independently edited guide content is preserved.
    with HTML.open("r", encoding="utf-8", newline="") as handle:
        current_html = handle.read()
    updated_html = IMAGE_TAG.sub(update_tag, current_html)
    with HTML.open("w", encoding="utf-8", newline="") as handle:
        handle.write(updated_html)
    (OUTPUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    original_bytes = sum(entry["originalBytes"] for entry in manifest.values())
    preview_bytes = sum(entry["previewBytes"] for entry in manifest.values())
    print(json.dumps({
        "screenshots": len(manifest),
        "originalMiB": round(original_bytes / 1024**2, 2),
        "previewMiB": round(preview_bytes / 1024**2, 2),
        "reductionPercent": round((1 - preview_bytes / original_bytes) * 100, 1),
        "fullSizePixels": "verified identical to originals",
    }), flush=True)


if __name__ == "__main__":
    main()
