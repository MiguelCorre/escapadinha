"""A promotion's images on the website, from its rendered slides (PNG, 1080 wide):
`slide_NN.webp` per slide (what the pages show), `slide_NN.jpg` per slide (what Instagram
fetches: its API takes JPEG only, D36), `thumb.webp` (540 wide) and `og.jpg` (Open Graph) from
the cover. The paths are the ones the contract names (`website.deal_image_paths`) and the
publisher uses (`website.deal_jpeg_paths`); the Astro build (`website.astro`, D35) writes
them with this function."""

from __future__ import annotations

from pathlib import Path

from PIL import Image


def write_promo_images(folder: Path, out: Path) -> list[str]:
    """Convert `folder`'s slides into `out`; returns the file names written, slides first."""
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for png in sorted(folder.glob("slide_*.png")):
        with Image.open(png) as im:
            rgb = im.convert("RGB")
            rgb.save(out / f"{png.stem}.webp", "WEBP", quality=80, method=6)
            rgb.save(out / f"{png.stem}.jpg", "JPEG", quality=90, optimize=True, progressive=True)
        written += [f"{png.stem}.webp", f"{png.stem}.jpg"]
    cover = folder / "slide_01.png"
    if cover.exists():
        with Image.open(cover) as im:
            rgb = im.convert("RGB")
            rgb.resize((540, 675), Image.LANCZOS).save(out / "thumb.webp", "WEBP", quality=78, method=6)
            rgb.save(out / "og.jpg", "JPEG", quality=82, optimize=True, progressive=True)
        written += ["thumb.webp", "og.jpg"]
    return written
