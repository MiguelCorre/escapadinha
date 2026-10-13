"""Ponto Nómada design tokens (design system, issue #12): one source for slides, docs and tests.

Direction A "Caderno de Viagem" (DECISIONS D20) is the base palette; this module adds the state
colours (success, warning, expired), the photo/scrim rules, type scales, spacing, radii and
shadows. `docs/design/tokens.json` is generated from `tailwind()`:

    uv run python -c "from escapadinha.renderer import tokens; tokens.write_json()"

and a test keeps the two identical and every text pair above its WCAG minimum.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from escapadinha.design_directions.contrast import MINIMUM, over, ratio
from escapadinha.design_directions.directions import CADERNO

# --- colour -------------------------------------------------------------------------------------

STATES = {
    "light": {
        "success": "#2F6830", "success-bg": "#E4EEDC",     # "abaixo do habitual", live deal
        "warning": "#835400", "warning-bg": "#F6EACB",     # remote airport, warming up, check
        "expired": "#8F1D33", "expired-bg": "#F7E1DF",     # expired deal: never a booking link
    },
    "dark": {
        "success": "#93C98C", "success-bg": "#1D2A1B",
        "warning": "#E3B65C", "warning-bg": "#2D2514",
        "expired": "#F4A3AE", "expired-bg": "#331A1D",
    },
}

# Text on photographs is always paper-coloured and sits on a warm-ink scrim. Contrast is measured
# against the scrim composited over a pure white pixel (the worst possible photo).
PHOTO_INK = "#FFFDF8"
SCRIM = "#16140F"
SCRIM_TEXT_ALPHA = 0.70          # minimum scrim opacity wherever text sits on a photo
SCRIM_RGB = " ".join(str(int(SCRIM[i:i + 2], 16)) for i in (1, 3, 5))   # '22 20 15' for CSS rgb()

PALETTE = {mode: {**CADERNO.palette(mode), **STATES[mode]} for mode in ("light", "dark")}


@dataclass(frozen=True)
class Pair:
    label: str
    fg: str          # token name or literal colour
    bg: str          # token name; 'photo' = scrim at SCRIM_TEXT_ALPHA over white
    role: str        # body | large | ui


PAIRS = (
    Pair("Ink on paper", "ink", "bg", "body"),
    Pair("Ink on card", "ink", "surface", "body"),
    Pair("Muted on paper", "muted", "bg", "body"),
    Pair("Muted on card", "muted", "surface", "body"),
    Pair("Accent (links, labels) on paper", "accent", "bg", "body"),
    Pair("Accent on card", "accent", "surface", "body"),
    Pair("Button text on accent", "on-accent", "accent", "body"),
    Pair("Success on paper", "success", "bg", "body"),
    Pair("Success on card", "success", "surface", "body"),
    Pair("Success on its tint", "success", "success-bg", "body"),
    Pair("Ink on success tint", "ink", "success-bg", "body"),
    Pair("Warning on paper", "warning", "bg", "body"),
    Pair("Warning on card", "warning", "surface", "body"),
    Pair("Warning on its tint", "warning", "warning-bg", "body"),
    Pair("Ink on warning tint", "ink", "warning-bg", "body"),
    Pair("Expired on paper", "expired", "bg", "body"),
    Pair("Expired on card", "expired", "surface", "body"),
    Pair("Expired on its tint", "expired", "expired-bg", "body"),
    Pair("Ink on expired tint", "ink", "expired-bg", "body"),
    Pair("Muted on expired tint", "muted", "expired-bg", "body"),
    Pair("Text on photo (scrim over white, worst case)", PHOTO_INK, "photo", "body"),
)


@dataclass(frozen=True)
class ContrastRow:
    mode: str
    label: str
    fg: str
    bg: str
    ratio: float
    minimum: float

    @property
    def ok(self) -> bool:
        return self.ratio >= self.minimum


def resolve(mode: str, token: str) -> str:
    if token == "photo":
        return over(SCRIM, SCRIM_TEXT_ALPHA, "#FFFFFF")
    return PALETTE[mode].get(token, token)


def contrast(palette: dict[str, dict[str, str]] | None = None) -> list[ContrastRow]:
    """Every text pair in light and dark, with its WCAG 2.2 ratio and minimum."""
    pal = palette or PALETTE
    rows = []
    for mode in ("light", "dark"):
        for p in PAIRS:
            fg = pal[mode].get(p.fg, p.fg)
            bg = over(SCRIM, SCRIM_TEXT_ALPHA, "#FFFFFF") if p.bg == "photo" else pal[mode][p.bg]
            rows.append(ContrastRow(mode, p.label, fg, bg, round(ratio(fg, bg), 2), MINIMUM[p.role]))
    return rows


# --- type ---------------------------------------------------------------------------------------

FONT_FAMILY = {
    "display": ["Fraunces", "Iowan Old Style", "Georgia", "serif"],        # headlines, prices
    "text": ["Source Serif 4", "Georgia", "Times New Roman", "serif"],      # body, data, labels
}

# Self-hosted WOFF2 files in assets/fonts/ (Latin subset of the Google Fonts variable fonts).
FONT_FILES = (
    ("Fraunces", "normal", "Fraunces-Roman.woff2"),
    ("Fraunces", "italic", "Fraunces-Italic.woff2"),
    ("Source Serif 4", "normal", "SourceSerif4-Roman.woff2"),
    ("Source Serif 4", "italic", "SourceSerif4-Italic.woff2"),
)

# Web scale (16 px root). Tailwind shape: [size, {lineHeight, letterSpacing, fontWeight}].
FONT_SIZE = {
    "display-xl": ["4.5rem", {"lineHeight": "1", "letterSpacing": "-0.01em", "fontWeight": "500"}],
    "display": ["3.5rem", {"lineHeight": "1.05", "letterSpacing": "-0.005em", "fontWeight": "500"}],
    "headline": ["2.25rem", {"lineHeight": "1.1", "letterSpacing": "0", "fontWeight": "600"}],
    "title": ["1.5rem", {"lineHeight": "1.2", "letterSpacing": "0", "fontWeight": "600"}],
    "price-xl": ["4rem", {"lineHeight": "1", "letterSpacing": "-0.02em", "fontWeight": "600"}],
    "price": ["2.5rem", {"lineHeight": "1", "letterSpacing": "-0.01em", "fontWeight": "600"}],
    "lead": ["1.25rem", {"lineHeight": "1.55", "letterSpacing": "0", "fontWeight": "400"}],
    "body": ["1.125rem", {"lineHeight": "1.6", "letterSpacing": "0", "fontWeight": "400"}],
    "small": ["0.9375rem", {"lineHeight": "1.5", "letterSpacing": "0", "fontWeight": "400"}],
    "label": ["0.8125rem", {"lineHeight": "1.3", "letterSpacing": "0.14em", "fontWeight": "600"}],
    "caption": ["0.8125rem", {"lineHeight": "1.4", "letterSpacing": "0", "fontWeight": "400"}],
}

# Instagram slides, 1080×1350 px. A slide is seen at ~390 CSS px wide on a phone (×0.36), so
# nothing that must be read goes below 28 px (≈10 px on the phone).
SLIDE_FONT_SIZE = {
    "display-xl": "132px", "display": "96px", "headline": "64px", "title": "52px",
    "price-xl": "232px", "price": "120px", "lead": "44px", "body": "40px", "small": "30px",
    "label": "28px", "caption": "28px",
}

# --- space, radii, shadows ----------------------------------------------------------------------

SPACING = {
    "2xs": "0.25rem", "xs": "0.5rem", "sm": "0.75rem", "md": "1rem", "lg": "1.5rem",
    "xl": "2rem", "2xl": "3rem", "3xl": "4rem", "4xl": "6rem",
}
SLIDE_SPACING = {"gutter": "72px", "card-pad": "52px", "stack": "28px"}

BORDER_RADIUS = {"none": "0", "sm": "2px", "md": "4px", "full": "9999px"}

BOX_SHADOW = {
    "none": "none",
    "card": "0 1px 0 rgba(30, 27, 22, 0.06), 0 10px 28px -14px rgba(30, 27, 22, 0.28)",
    "lifted": "0 2px 0 rgba(30, 27, 22, 0.08), 0 28px 60px -24px rgba(22, 20, 15, 0.6)",
    "focus": "0 0 0 3px var(--pn-accent)",
}


def tailwind() -> dict:
    """The machine-readable tokens (`docs/design/tokens.json`).

    `colors` point at CSS variables so one Tailwind class works in light and dark; `themes` holds
    the values to emit as `--pn-*` variables (`:root` = light, `prefers-color-scheme: dark` = dark).
    """
    names = list(PALETTE["light"])
    return {
        "$schema-note": ("Ponto Nómada design tokens (docs/design/design-system.md). Generated by "
                         "renderer/tokens.py (tokens.write_json()); do not edit by hand. "
                         "Spread colors/fontFamily/fontSize/spacing/borderRadius/boxShadow into "
                         "Tailwind theme.extend; emit themes.light/dark as --pn-* CSS variables."),
        "themes": {mode: dict(PALETTE[mode]) for mode in ("light", "dark")},
        "photo": {"ink": PHOTO_INK, "scrim": SCRIM, "scrimTextAlpha": SCRIM_TEXT_ALPHA},
        "colors": {name: f"var(--pn-{name})" for name in names},
        "fontFamily": FONT_FAMILY,
        "fontSize": FONT_SIZE,
        "spacing": SPACING,
        "borderRadius": BORDER_RADIUS,
        "boxShadow": BOX_SHADOW,
        "slides": {"width": 1080, "height": 1350, "fontSize": SLIDE_FONT_SIZE,
                   "spacing": SLIDE_SPACING},
    }


def css_vars(mode: str) -> str:
    """`--pn-bg: #F5F0E6; ...` for one mode (used by the slide templates)."""
    return " ".join(f"--pn-{k}: {v};" for k, v in PALETTE[mode].items())


def tokens_json() -> str:
    return json.dumps(tailwind(), ensure_ascii=False, indent=2) + "\n"


def write_json(path: str | Path = "docs/design/tokens.json") -> Path:
    """Regenerate the JSON tokens (run from the repo root)."""
    path = Path(path)
    path.write_text(tokens_json(), encoding="utf-8", newline="\n")
    return path
