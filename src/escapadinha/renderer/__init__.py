"""HTML/CSS slide templates rendered to 1080×1350 PNG with Playwright (Chromium).

Assets (photo, fonts, logo) are inlined so pages render offline from about:blank. Colours, type
and spacing come from the design system tokens (`renderer.tokens`, docs/design/design-system.md).
"""

from __future__ import annotations

import base64
import mimetypes
from pathlib import Path

from jinja2 import Environment, PackageLoader, StrictUndefined
from playwright.sync_api import sync_playwright

from escapadinha.config import Brand
from escapadinha.guides import Guide
from escapadinha.presentation import DISCLOSURE, DealView, PhotoCredit
from escapadinha.renderer import tokens

WIDTH, HEIGHT = 1080, 1350
mimetypes.add_type("font/woff2", ".woff2")


def data_uri(path: Path | None) -> str | None:
    if path is None or not path.exists():
        return None
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"


class SlideRenderer:
    """Context manager holding one Chromium page; render many slides with it."""

    def __init__(self, assets_dir: Path, brand: Brand):
        self._env = Environment(loader=PackageLoader("escapadinha.renderer", "templates"),
                                autoescape=True, undefined=StrictUndefined)
        self._brand = brand
        # Light logo (ink) for paper slides, dark logo (paper-coloured) for photos and dark slides.
        self._logos = {v: (assets_dir / f"logo-{v}.svg").read_text("utf-8") for v in ("light", "dark")}
        # Self-hosted OFL fonts; a missing file falls back to the next family in the stack.
        self._fonts = [(family, style, uri) for family, style, name in tokens.FONT_FILES
                       if (uri := data_uri(assets_dir / "fonts" / name))]

    def __enter__(self) -> SlideRenderer:
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch()
        self._page = self._browser.new_page(viewport={"width": WIDTH, "height": HEIGHT},
                                            device_scale_factor=1)
        return self

    def __exit__(self, *exc) -> None:
        self._browser.close()
        self._pw.stop()

    def _render(self, template: str, out: Path, **ctx) -> Path:
        html = self._env.get_template(template).render(
            brand=self._brand, logos=self._logos, fonts=self._fonts, t=tokens, **ctx)
        self._page.set_content(html, wait_until="load")
        self._page.evaluate("document.fonts.ready.then(() => window.fitText())")
        out.parent.mkdir(parents=True, exist_ok=True)
        self._page.screenshot(path=str(out), clip={"x": 0, "y": 0, "width": WIDTH, "height": HEIGHT})
        return out

    def render_deal(self, view: DealView, photo_path: Path | None, out_dir: Path) -> list[Path]:
        photo_uri = data_uri(photo_path)
        return [
            self._render(f"deal/slide_{n}.html.j2", out_dir / f"slide_{n:02d}.png", v=view,
                         photo_uri=photo_uri, slide_no=n, total_slides=3)
            for n in (1, 2, 3)
        ]

    def render_guide(self, guide: Guide, photo: PhotoCredit, photo_path: Path | None,
                     out_dir: Path) -> list[Path]:
        photo_uri = data_uri(photo_path)
        total = len(guide.tips) + 2
        common = dict(g=guide, photo=photo, photo_uri=photo_uri, total_slides=total,
                      disclosure=DISCLOSURE)
        paths = [self._render("guide/cover.html.j2", out_dir / "slide_01.png", slide_no=1, **common)]
        for i, tip in enumerate(guide.tips, start=1):
            paths.append(self._render("guide/tip.html.j2", out_dir / f"slide_{i + 1:02d}.png",
                                      slide_no=i + 1, tip=tip, index=i, **common))
        paths.append(self._render("guide/cta.html.j2", out_dir / f"slide_{total:02d}.png",
                                  slide_no=total, **common))
        return paths
