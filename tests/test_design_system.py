"""Design system (#12): JSON tokens match the palette in code, every pair passes WCAG, assets ship."""

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from escapadinha.design_directions.directions import CADERNO
from escapadinha.renderer import tokens

REPO = Path(__file__).parent.parent
TOKENS_JSON = REPO / "docs" / "design" / "tokens.json"


def load() -> dict:
    return json.loads(TOKENS_JSON.read_text("utf-8"))


def test_json_is_generated_from_code():
    assert load() == json.loads(tokens.tokens_json()), \
        "docs/design/tokens.json is stale: run tokens.write_json()"


@pytest.mark.parametrize("mode", ["light", "dark"])
def test_json_themes_extend_direction_a(mode):
    theme = load()["themes"][mode]
    # The chosen direction's palette (D20) is the base, unchanged.
    assert {k: theme[k] for k in CADERNO.palette(mode)} == CADERNO.palette(mode)
    assert {"success", "success-bg", "warning", "warning-bg", "expired", "expired-bg"} <= set(theme)


def test_json_shape_is_tailwind_ready():
    data = load()
    for key in ("colors", "fontFamily", "fontSize", "spacing", "borderRadius", "boxShadow"):
        assert data[key], key
    # Each colour is a CSS variable whose value exists in both themes.
    for name, value in data["colors"].items():
        assert value == f"var(--pn-{name})"
        assert name in data["themes"]["light"] and name in data["themes"]["dark"]
    assert data["fontFamily"]["display"][0] == "Fraunces"
    assert data["fontFamily"]["text"][0] == "Source Serif 4"
    for size, opts in data["fontSize"].values():
        assert size.endswith("rem") and "lineHeight" in opts


def test_every_pair_in_the_json_passes_wcag_aa():
    data = load()
    rows = tokens.contrast(data["themes"])
    assert {r.mode for r in rows} == {"light", "dark"}
    failing = [(r.mode, r.label, r.ratio, r.minimum) for r in rows if not r.ok]
    assert not failing
    assert data["photo"]["scrimTextAlpha"] >= 0.7


def test_fonts_are_self_hosted_with_licences():
    fonts = REPO / "assets" / "fonts"
    for _, _, name in tokens.FONT_FILES:
        assert (fonts / name).read_bytes()[:4] == b"wOF2", name
    for licence in ("OFL-Fraunces.txt", "OFL-SourceSerif4.txt"):
        assert "SIL Open Font License" in (fonts / licence).read_text("utf-8")


@pytest.mark.parametrize("variant", ["light", "dark"])
def test_logo_variants_are_outlined_svg(variant):
    path = REPO / "assets" / f"logo-{variant}.svg"
    root = ET.fromstring(path.read_text("utf-8"))
    assert root.tag.endswith("svg") and root.get("aria-label") == "Ponto Nómada"
    # Outlined wordmark: renders the same without the font installed.
    assert not root.findall(".//{http://www.w3.org/2000/svg}text")
    ink = tokens.PALETTE["light"]["ink"] if variant == "light" else tokens.PHOTO_INK
    assert ink in path.read_text("utf-8")
