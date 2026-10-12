"""Generate lossless WebP screenshots and update the guide's image references.

Run with Python and Pillow installed: python scripts/optimize_screenshots.py
Existing full-size WebP files are the sources for regenerating previews, so
original PNGs are not required. New source images are removed after conversion
only when index.html no longer references them. Full-size WebP files preserve
every decoded pixel; previews fit within 1600 pixels for the content column.
"""

import json
import re
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parent.parent
HTML = ROOT / "index.html"
OUTPUT = ROOT / "images" / "optimized"
IMAGE_TAG = re.compile(r"<img\b[^>]*>")


def source_path(tag):
    match = re.search(r'(?<![\w-])src="(images/[^\"]+)"', tag)
    if not match:
        return None
    src = match.group(1)
    if src.startswith("images/optimized/"):
        full = re.search(r'data-full-src="(images/[^\"]+)"', tag)
        if full:
            return full.group(1)
        if src.endswith(".preview.webp"):
            return src.removesuffix(".preview.webp") + ".webp"
    return src


def save_lossless(pixels, target):
    """Reuse an identical image instead of recompressing it on every run."""
    if target.exists():
        with Image.open(target) as existing:
            if existing.size == pixels.size and existing.convert(pixels.mode).tobytes() == pixels.tobytes():
                return
    pixels.save(target, "WEBP", lossless=True, exact=True, method=6)


def main():
    sources = sorted(
        {path for tag in IMAGE_TAG.findall(HTML.read_text(encoding="utf-8"))
         if (path := source_path(tag))}
    )
    OUTPUT.mkdir(exist_ok=True)
    manifest = {}
    converted_sources = []
    output_owners = {}
    for path in sources:
        source = (ROOT / path).resolve()
        if not source.is_relative_to((ROOT / "images").resolve()):
            raise ValueError(f"Source is outside the images folder: {path}")
        full = OUTPUT / (source.stem + ".webp")
        if full in output_owners and output_owners[full] != source:
            raise ValueError(f"Screenshots need distinct filenames: {path}")
        output_owners[full] = source
        source_bytes = source.stat().st_size
        with Image.open(source) as image:
            mode = "RGBA" if "A" in image.getbands() else "RGB"
            pixels = image.convert(mode)
        # The input file is closed before writing, including when input is WebP.
        save_lossless(pixels, full)
        with Image.open(full) as decoded:
            if decoded.convert(mode).tobytes() != pixels.tobytes():
                raise ValueError(f"Full-size screenshot changed pixels: {path}")

        preview = pixels.copy()
        preview.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
        preview_path = full
        if preview.size != pixels.size:
            preview_path = OUTPUT / (source.stem + ".preview.webp")
            save_lossless(preview, preview_path)
        manifest[path] = {
            "preview": preview_path.relative_to(ROOT).as_posix(),
            "full": full.relative_to(ROOT).as_posix(),
            "width": preview.width,
            "height": preview.height,
            "fullWidth": pixels.width,
            "fullHeight": pixels.height,
            "sourceBytes": source_bytes,
            "previewBytes": preview_path.stat().st_size,
        }
        if source != full.resolve():
            converted_sources.append(source)

    def update_tag(match):
        tag = match.group(0)
        path = source_path(tag)
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
    removed_sources = 0
    for source in converted_sources:
        relative = source.relative_to(ROOT).as_posix()
        if relative not in updated_html:
            source.unlink()
            removed_sources += 1
    source_bytes = sum(entry["sourceBytes"] for entry in manifest.values())
    preview_bytes = sum(entry["previewBytes"] for entry in manifest.values())
    print(json.dumps({
        "screenshots": len(manifest),
        "sourceMiB": round(source_bytes / 1024**2, 2),
        "previewMiB": round(preview_bytes / 1024**2, 2),
        "removedConvertedSources": removed_sources,
        "fullSizePixels": "verified identical to source images",
    }), flush=True)


if __name__ == "__main__":
    main()
